"""Telegram sloj: prima tekst, glas, slike i fajlove, šalje odgovore i dugmad.

Ovde nema "pameti" — sve odluke donosi agent. Bot samo pretvara Telegram
poruke u ulaz za agenta i odgovor nazad u Telegram poruke.
"""

import asyncio
import base64
import logging

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

from apu import memory, status, usage
from apu.agent import history, loop
from apu.config import settings
from apu.pismo import ima_cirilice, u_latinicu
from apu.rag.ingest import ingest_file
from apu.tools import registry
from apu.transcribe import transcribe

log = logging.getLogger(__name__)

TG_LIMIT = 4000
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Istorija se učitava i dopisuje u istoj razmeni, pa sledeća mora da sačeka.
_chat_locks: dict[int, asyncio.Lock] = {}


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
            result = await loop.run(chat_id, content)
    except Exception:
        log.exception("Agent pukao")
        await ctx.bot.send_message(chat_id, "⚠️ Nešto je puklo. Probaj ponovo za koji trenutak.")
        return
    finally:
        stop.set()
        await typing

    if ima_cirilice(result.text):
        log.warning("Model je odlutao u ćirilicu — preslovljavam.")
    for part in _split(u_latinicu(result.text)):
        await ctx.bot.send_message(chat_id, part)

    for token, opis in result.pending:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Potvrdi", callback_data=f"ok:{token}"),
              InlineKeyboardButton("❌ Otkaži", callback_data=f"no:{token}")]]
        )  # fmt: skip
        await ctx.bot.send_message(chat_id, f"Čeka potvrdu:\n{u_latinicu(opis)}", reply_markup=kb)


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
    n, poruka = await ingest_file(doc.file_name, data)
    await update.message.reply_text(f"📄 {doc.file_name}: {poruka}")
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
        reply = f"{q.message.text}\n\n✅ Izvršeno.\n{u_latinicu(result)[:3000]}"
        note = f"[Sistem: korisnik je potvrdio akciju. Rezultat: {result[:1500]}]"
    else:
        registry.cancel(token)
        reply = f"{q.message.text}\n\n❌ Otkazano."
        note = "[Sistem: korisnik je otkazao predloženu akciju.]"
    # Agent mora da zna šta se desilo sa akcijom kad nastavi razgovor.
    await history.add_note(update.effective_chat.id, note)
    await q.edit_message_text(u_latinicu(reply))


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        await update.message.reply_text(
            "Zdravo! Ovde sam. Pričaj, pitaj, šalji glasovne i fajlove."
        )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        await history.clear(update.effective_chat.id)
        await update.message.reply_text(
            "🧹 Istorija razgovora obrisana. Dugoročna memorija ostaje."
        )


async def cmd_costs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        days = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else 7
        await update.message.reply_text(await usage.report(days))


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _owner(update):
        for part in _split(u_latinicu(await status.report())):
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
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("troskovi", cmd_costs))
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
