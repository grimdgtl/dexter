"""Telegram sloj: prima tekst, glas, slike i fajlove, šalje odgovore i dugmad.

Ovde nema "pameti" — sve odluke donosi agent. Bot samo pretvara Telegram
poruke u ulaz za agenta i odgovor nazad u Telegram poruke.
"""

import asyncio
import base64
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from apu import jobs, memory, receipts, status, usage
from apu.agent import history, loop
from apu.config import settings
from apu.pismo import u_latinicu
from apu.rag.ingest import ingest_file
from apu.tools import registry
from apu.transcribe import transcribe

log = logging.getLogger(__name__)

TG_LIMIT = 4000
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Istorija se učitava i dopisuje u istoj razmeni, pa sledeća mora da sačeka.
_chat_locks: dict[int, asyncio.Lock] = {}


class StreamingReply:
    """Ograničen prikaz je odvojen od celovitog odgovora i istorije agenta."""

    def __init__(self, bot, chat_id):
        self.bot, self.chat_id = bot, chat_id
        self.messages = []
        self.text = ""
        self.last_write = -float("inf")
        self.disabled = False

    async def update(self, text):
        text = u_latinicu(text)
        if not text:
            # Tekst pre poziva alata ostaje zasebna poruka, a sledeći korak počinje novi prikaz.
            self.messages = []
            self.text = ""
            return
        self.text = text
        await self.flush()

    async def flush(self):
        if self.disabled:
            return False
        parts = [self.text[i : i + TG_LIMIT] for i in range(0, len(self.text), TG_LIMIT)]
        try:
            for i, part in enumerate(parts):
                if i == len(self.messages):
                    sent = await self.bot.send_message(self.chat_id, part)
                    self.messages.append((sent.message_id, part))
                    self.last_write = time.monotonic()
                elif self.messages[i][1] != part:
                    if time.monotonic() - self.last_write < 1:
                        return False
                    await self.bot.edit_message_text(
                        part, chat_id=self.chat_id, message_id=self.messages[i][0]
                    )
                    self.messages[i] = (self.messages[i][0], part)
                    self.last_write = time.monotonic()
            return bool(parts)
        except Exception as exc:
            log.warning("Prikaz streama nije uspeo (%s).", type(exc).__name__)
            self.disabled = True
            return False

    async def finish(self, text):
        await self.update(text)
        while not self.disabled:
            if await self.flush():
                return True
            await asyncio.sleep(max(0, 1 - (time.monotonic() - self.last_write)))
        return False


def _owner(update: Update) -> bool:
    return update.effective_chat is not None and (
        update.effective_chat.id == settings().telegram_owner_chat_id
    )


def _split(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Deli dugačak odgovor na delove, po mogućnosti na novom redu."""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    return [*parts, text] if text else parts


async def _keep_typing(bot, chat_id: int, stop: asyncio.Event) -> None:
    """Telegram gasi 'kuca…' posle 5 s, pa ga obnavljamo dok agent radi."""
    while not stop.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except TimeoutError:
            pass


async def _answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, content) -> None:
    chat_id = update.effective_chat.id
    stop = asyncio.Event()
    typing = asyncio.create_task(_keep_typing(ctx.bot, chat_id, stop))
    try:
        lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            preview = StreamingReply(ctx.bot, chat_id) if settings().streaming == "on" else None
            kwargs = {"on_text": preview.update} if preview else {}
            result = await loop.run(chat_id, content, **kwargs)
            delivered = await preview.finish(result.text) if preview else False
            if not delivered:
                for part in _split(u_latinicu(result.text)):
                    await ctx.bot.send_message(chat_id, part)
            for token, opis in result.pending:
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("✅ Potvrdi", callback_data=f"ok:{token}"),
                            InlineKeyboardButton("❌ Otkaži", callback_data=f"no:{token}"),
                        ]
                    ]
                )
                parts = _split(u_latinicu(f"Čeka potvrdu:\n{opis}"))
                for i, part in enumerate(parts):
                    await ctx.bot.send_message(
                        chat_id, part, **({"reply_markup": kb} if i == len(parts) - 1 else {})
                    )
    except Exception:
        log.exception("Agent pukao")
        await ctx.bot.send_message(chat_id, "⚠️ Nešto je puklo. Probaj ponovo za koji trenutak.")
        return
    finally:
        stop.set()
        await typing


# ── Handleri ────────────────────────────────────────────────


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        await _answer(update, ctx, update.message.text)


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    voice = update.message.voice or update.message.audio
    data = bytes(await (await voice.get_file()).download_as_bytearray())
    try:
        text = await transcribe(data)
    except Exception:
        log.exception("Transkripcija pukla")
        await update.message.reply_text("⚠️ Nisam uspeo da razumem glasovnu poruku.")
        return
    await update.message.reply_text(f"🎙️ {text}")
    await _answer(update, ctx, text)


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    msg = update.message
    if msg.photo:
        file, mime = await msg.photo[-1].get_file(), "image/jpeg"
    else:
        file, mime = await msg.document.get_file(), msg.document.mime_type
    data = bytes(await file.download_as_bytearray())
    blocks = [
        {"type": "image",
         "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}},
        {"type": "text", "text": msg.caption or "Šta vidiš na slici? Izdvoj bitne podatke."},
    ]  # fmt: skip
    await _answer(update, ctx, blocks)


async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """PDF/tekst fajl → u bazu znanja, pa agent dobije poruku da je stigao."""
    if not _owner(update):
        return
    doc = update.message.document
    data = bytes(await (await doc.get_file()).download_as_bytearray())
    try:
        n, poruka = await ingest_file(doc.file_name, data)
    except ValueError as exc:
        await update.message.reply_text(u_latinicu(f"⚠️ {exc}"))
        return
    except Exception:
        log.exception("Uvoz dokumenta nije uspeo")
        await update.message.reply_text(
            "⚠️ Uvoz nije uspeo. Proveri fajl i OCR_MAX_PAGES za skenove."
        )
        return
    await update.message.reply_text(u_latinicu(f"📄 {doc.file_name}: {poruka}"))
    if n and update.message.caption:
        await _answer(update, ctx, f"(Upravo sam ti poslao fajl {doc.file_name}.) "
                                   f"{update.message.caption}")  # fmt: skip


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not _owner(update):
        return
    await q.answer()
    action, token = q.data.split(":", 1)
    if action == "ok":
        result = await registry.confirm(token)
        outcome = (
            "⚠️ Nije izvršeno." if result.startswith(("Greška:", "Ova akcija")) else "✅ Izvršeno."
        )
        reply = f"{q.message.text}\n\n{outcome}\n{u_latinicu(result)[:3000]}"
        note = f"[Sistem: korisnik je potvrdio akciju. Rezultat: {result[:1500]}]"
    else:
        registry.cancel(token)
        reply = f"{q.message.text}\n\n❌ Otkazano."
        note = "[Sistem: korisnik je otkazao predloženu akciju.]"
    # Agent mora da zna šta se desilo sa akcijom kad nastavi razgovor.
    await history.add_note(update.effective_chat.id, note)
    parts = _split(u_latinicu(reply))
    await q.edit_message_text(parts[0])
    for part in parts[1:]:
        await ctx.bot.send_message(update.effective_chat.id, part)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        await update.message.reply_text(
            "Zdravo! Ovde sam. Pričaj, pitaj, šalji glasovne i fajlove."
        )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        chat_id = update.effective_chat.id
        async with _chat_locks.setdefault(chat_id, asyncio.Lock()):
            await history.clear(chat_id)
        await update.message.reply_text(
            "🧹 Istorija razgovora obrisana. Dugoročna memorija ostaje."
        )


async def cmd_costs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        days = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else 7
        await update.message.reply_text(await usage.report(days))


async def cmd_expenses(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    try:
        if len(ctx.args) > 1:
            raise ValueError("Upotreba: /rashodi [YYYY-MM].")
        text = await receipts.report(ctx.args[0] if ctx.args else None)
    except ValueError as exc:
        text = str(exc)
    for part in _split(u_latinicu(text)):
        await update.message.reply_text(part)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        for part in _split(u_latinicu(await status.report())):
            await update.message.reply_text(part)


async def cmd_jobs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    try:
        hours = int(ctx.args[0]) if ctx.args else 24
        text = await jobs.report(hours)
    except ValueError:
        text = "Upotreba: /poslovi [sati], broj sati između 1 i 8760."
    for part in _split(u_latinicu(text)):
        await update.message.reply_text(part)


async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    facts = await memory.list_all()
    if not facts:
        await update.message.reply_text("Memorija je prazna.")
        return
    lines = [f"[{f['id']}] ({f['category']}) {f['text']}" for f in facts[:60]]
    for part in _split(f"🧠 Pamtim {len(facts)} činjenica:\n" + "\n".join(lines)):
        await update.message.reply_text(part)


def build(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("poslovi", cmd_jobs))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("troskovi", cmd_costs))
    app.add_handler(CommandHandler("rashodi", cmd_expenses))
    app.add_handler(CommandHandler("memorija", cmd_memory))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(
        MessageHandler(filters.Document.MimeType("image/jpeg") | filters.Document.MimeType(
            "image/png") | filters.Document.MimeType("image/webp"), on_photo)
    )  # fmt: skip
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    # /duboko ide agentu kao tekst (router ga prepoznaje), ostale komande ne.
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND | filters.Regex(r"^/duboko")),
                                   on_text))  # fmt: skip
