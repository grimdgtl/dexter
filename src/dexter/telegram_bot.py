"""Telegram sloj: prima tekst, glas, slike i fajlove, šalje odgovore i dugmad.

Ovde nema "pameti" — sve odluke donosi agent. Bot samo pretvara Telegram
poruke u ulaz za agenta i odgovor nazad u Telegram poruke.
"""

import asyncio
import base64
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dexter import feedback, jobs, memory, receipts, status, tts, usage
from dexter.agent import history, loop
from dexter.config import settings
from dexter.contracts import intake as contract_intake
from dexter.contracts import service as contract_service
from dexter.pismo import u_latinicu
from dexter.rag.ingest import ingest_file
from dexter.services import notion_task_map, schema
from dexter.tools import registry
from dexter.transcribe import transcribe

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


async def _answer(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, content, *, voice_input=False
) -> None:
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
                document = registry.pending_document(token)
                if document:
                    try:
                        await ctx.bot.send_document(
                            chat_id, InputFile(document.data, filename=document.filename)
                        )
                    except Exception:
                        # Bez poslatog PDF-a korisnik nema šta da pregleda pre potvrde.
                        for pending_token, _ in result.pending:
                            registry.cancel(pending_token)
                        raise
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                registry.pending_confirm_label(token), callback_data=f"ok:{token}"
                            ),
                            InlineKeyboardButton(
                                registry.pending_cancel_label(token), callback_data=f"no:{token}"
                            ),
                        ]
                    ]
                )
                parts = _split(u_latinicu(f"Čeka potvrdu:\n{opis}"))
                for i, part in enumerate(parts):
                    await ctx.bot.send_message(
                        chat_id, part, **({"reply_markup": kb} if i == len(parts) - 1 else {})
                    )
            if tts.requested(content, voice_input=voice_input) and result.text.strip():
                try:
                    i = 0
                    async for audio in tts.synthesize(u_latinicu(result.text)):
                        i += 1
                        await ctx.bot.send_voice(
                            chat_id,
                            InputFile(audio, filename=f"odgovor-{i}.ogg"),
                            caption=f"AI generisan glas · deo {i}",
                        )
                except Exception as exc:
                    log.warning("Glasovni dodatak nije uspeo (%s).", type(exc).__name__)
                    await ctx.bot.send_message(
                        chat_id,
                        "Tekst je poslat. Glasovni dodatak nije uspeo; proveri OPENAI_API_KEY i TTS podešavanja.",
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
        text = u_latinicu(await transcribe(data))
    except Exception:
        log.exception("Transkripcija pukla")
        await update.message.reply_text("⚠️ Nisam uspeo da razumem glasovnu poruku.")
        return
    await update.message.reply_text(u_latinicu(f"🎙️ {text}"))
    await _answer(update, ctx, text, voice_input=True)


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    msg = update.message
    if await _route_contract_attachment(update, ctx):
        return
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
    if await _route_contract_attachment(update, ctx):
        return
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


def contract_requested(caption: str | None) -> bool:
    parts = (caption or "").split(maxsplit=1)
    return bool(parts and parts[0].split("@")[0].lower() == "/ugovor")


async def _route_contract_attachment(update, ctx):
    msg = update.message
    try:
        if contract_requested(msg.caption):
            await contract_intake.cancel(update.effective_chat.id)
        elif not await contract_intake.consume(update.effective_chat.id, msg.message_id):
            return False
    except Exception as exc:
        # Pri nepoznatom režimu ne šaljemo dokument u drugi, plaćeni tok obrade.
        log.warning("Izbor pregleda ugovora nije uspeo (%s).", type(exc).__name__)
        await msg.reply_text("⚠️ Ne mogu da proverim način obrade. Pošalji ponovo /ugovor pa fajl.")
        return True
    await _contract_attachment(update, ctx, msg)
    return True


async def _contract_attachment(update, ctx, msg):
    doc = getattr(msg, "document", None)
    photo = getattr(msg, "photo", None)
    attachment = photo[-1] if photo else doc
    name = (doc.file_name or "ugovor.pdf") if doc else "ugovor.jpg"
    mime = doc.mime_type if doc else "image/jpeg"
    if (getattr(attachment, "file_size", None) or 0) > contract_service.MAX_BYTES:
        await update.message.reply_text(
            "Ugovor mora biti manji od 10 MB. Pošalji manji fajl uz /ugovor."
        )
        return
    if mime not in {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
    } and not name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "Za pregled ugovora pošalji PDF, JPG, PNG ili WebP uz /ugovor."
        )
        return
    try:
        data = bytes(await (await attachment.get_file()).download_as_bytearray())
    except Exception as exc:
        log.warning("Preuzimanje ugovora nije uspelo (%s).", type(exc).__name__)
        await update.message.reply_text(
            "⚠️ Preuzimanje nije uspelo. Pošalji fajl ponovo uz /ugovor."
        )
        return
    await _contract_review(update, ctx, name, data, mime)


async def _show_contract(update, ctx, review):
    for part in _split(contract_service.render(review)):
        await ctx.bot.send_message(update.effective_chat.id, part)
    if not registry._TOOLS["contract_task_create"].is_enabled():
        await ctx.bot.send_message(
            update.effective_chat.id,
            "Za potvrdu Work zadataka podesi NOTION_API_KEY i NOTION_TASKS_DB_ID. Pregled ugovora je sačuvan.",
        )
        return
    for proposal in review.predlozi:
        outcome = await registry.execute(
            "contract_task_create", {"pregled_id": review.id, "predlog_id": proposal.id}
        )
        if outcome.pending is None:
            for part in _split(u_latinicu(outcome.text)):
                await ctx.bot.send_message(update.effective_chat.id, part)
            continue
        token, text = outcome.pending
        try:
            parts = _split(u_latinicu("Predlog — potvrdi samo ako želiš ovaj zadatak:\n" + text))
            for i, part in enumerate(parts):
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("✅ Sačuvaj zadatak", callback_data=f"ok:{token}"),
                            InlineKeyboardButton("❌ Odbaci", callback_data=f"no:{token}"),
                        ]
                    ]
                )
                await ctx.bot.send_message(
                    update.effective_chat.id,
                    part,
                    **({"reply_markup": keyboard} if i == len(parts) - 1 else {}),
                )
        except BaseException:
            registry.cancel(token)
            raise


async def _contract_review(update, ctx, name, data, mime):
    chat_id = update.effective_chat.id
    stop = asyncio.Event()
    typing = asyncio.create_task(_keep_typing(ctx.bot, chat_id, stop))
    try:
        async with _chat_locks.setdefault(chat_id, asyncio.Lock()):
            await ctx.bot.send_message(
                chat_id,
                "Čitam ugovor i proveravam citate. Posle pregleda biraš zadatke; ništa se ne zakazuje automatski.",
            )
            review = await contract_service.analyze(name, data, mime)
            await _show_contract(update, ctx, review)
    except Exception as exc:
        log.warning("Pregled ugovora nije uspeo (%s).", type(exc).__name__)
        text = (
            str(exc)
            if isinstance(exc, ValueError)
            else "Proveri fajl i log obrade. Pregled nije završen."
        )
        for part in _split(u_latinicu(f"⚠️ {text}")):
            await ctx.bot.send_message(chat_id, part)
    finally:
        stop.set()
        await typing


async def cmd_contract(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    try:
        chat_id = update.effective_chat.id
        if ctx.args == ["otkazi"]:
            await contract_intake.cancel(chat_id)
            await update.message.reply_text("Otkazano čekanje ugovora.")
            return
        if not ctx.args:
            replied = getattr(update.message, "reply_to_message", None)
            if replied and (getattr(replied, "document", None) or getattr(replied, "photo", None)):
                await contract_intake.cancel(chat_id)
                await _contract_attachment(update, ctx, replied)
            else:
                await contract_intake.arm(chat_id, update.message.message_id)
                await update.message.reply_text(
                    "Pošalji sledeći PDF ili fotografiju u narednih 10 minuta. Dobićeš pregled sa citatima i predloge za pojedinačnu potvrdu. Odustajanje: /ugovor otkazi. Možeš i da odgovoriš komandom /ugovor na već poslati fajl."
                )
            return
        await contract_intake.cancel(chat_id)
        async with _chat_locks.setdefault(update.effective_chat.id, asyncio.Lock()):
            await _show_contract(update, ctx, await contract_service.load(ctx.args[0]))
    except ValueError:
        await update.message.reply_text(
            "Pregled nije pronađen. Koristi /ugovor ID ili pošalji dokument uz opis /ugovor."
        )
    except Exception as exc:
        log.warning("Komanda ugovor nije uspela (%s).", type(exc).__name__)
        await update.message.reply_text("⚠️ Pregled nije dostupan. Probaj ponovo /ugovor.")


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not _owner(update):
        return
    await q.answer()
    action, token = q.data.split(":", 1)
    if action == "ok":
        result = await registry.confirm(token)
        document = None
        successful = True
        if isinstance(result, registry.ConfirmedAction):
            document, successful, result = result.document, result.successful, result.result
        outcome = (
            "⚠️ Nije potpuno izvršeno."
            if not successful
            else "⚠️ Nije izvršeno."
            if result.startswith(("Greška:", "Ova akcija"))
            else "✅ Izvršeno."
        )
        if document:
            try:
                await ctx.bot.send_document(
                    update.effective_chat.id,
                    InputFile(document.data, filename=document.filename),
                    caption="Sačuvana verzija fakture sa konačnim brojem.",
                )
            except Exception as exc:
                log.warning("Konačni PDF nije poslat (%s).", type(exc).__name__)
                result += (
                    "\nPDF nije ponovo poslat u Telegram; preuzmi sačuvanu verziju sa Drive linka."
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
            await contract_intake.cancel(chat_id)
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


async def cmd_schema(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner(update):
        return
    try:
        args = getattr(ctx, "args", None) or []
        if args == ["liste"]:
            text = notion_task_map.format_report(await notion_task_map.inspect())
        elif args:
            text = "Upotreba: /provera ili /provera liste."
        else:
            text = schema.format_report(await schema.check())
    except Exception as exc:
        log.warning("Ručna provera šema nije uspela (%s).", type(exc).__name__)
        text = "Nisam uspeo da proverim Notion šeme. Pokušaj ponovo za koji trenutak."
    for part in schema.parts(text):
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
    app.add_handler(CommandHandler("provera", cmd_schema))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("troskovi", cmd_costs))
    app.add_handler(CommandHandler("rashodi", cmd_expenses))
    app.add_handler(CommandHandler("memorija", cmd_memory))
    app.add_handler(CommandHandler("ugovor", cmd_contract))
    app.add_handler(CallbackQueryHandler(feedback.on_vote, pattern=r"^vote:"))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(ok|no):"))
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
