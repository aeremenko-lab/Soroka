import logging
import sqlite3
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

logger = logging.getLogger(__name__)

from src.adapters.jina import JinaClient
from src.adapters.deepgram import DeepgramClient
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
)
from src.bot.auth import is_owner, owner_only

PROMPTS = {
    "jina":      "Шаг 1/4 — ключ Jina.\nЗайди на jina.ai → API → Free tier.\nПришли ключ сообщением.",
    "deepgram":  "Шаг 2/4 — ключ Deepgram.\nЗайди на deepgram.com, создай API key.\nПришли ключ сообщением.",
    "github":    ("Шаг 3/4 — резервное копирование на GitHub (можно /skip).\n\n"
                  "Сначала создай **приватный** репозиторий на github.com/new "
                  "(имя любое, например `soroka-data`).\n\n"
                  "Когда создашь — пришли его сюда в формате `username/repo` "
                  "или ссылкой на GitHub."),
    "channel":   ("Шаг 4/4 — твой канал-инбокс.\n\n"
                  "Это твоё личное место в Telegram, куда ты будешь скидывать всё, "
                  "что хочешь сохранить (статьи, голосовые, ссылки, файлы). "
                  "Я индексирую каждое сообщение и потом ищу по ним.\n\n"
                  "Что нужно сделать:\n"
                  "1) Создай **приватный канал** в Telegram (название любое, "
                  "например «Избранное»).\n"
                  "2) Добавь меня в канал администратором с правами:\n"
                  "   • Post Messages (публиковать сообщения)\n"
                  "   • Add Reactions (ставить реакции)\n"
                  "3) **Сам напиши** в этом канале любое сообщение — например, "
                  "«привет». Нужно именно твоё новое сообщение, **не пересылка** "
                  "из чужого канала.\n"
                  "4) Это сообщение перешли сюда: долгое нажатие → «Переслать» "
                  "→ выбери этот чат с ботом."),
}

DONE_MESSAGE = (
    "Готово! Поехали.\n"
    "• /help — справка\n"
    "• /status — текущие настройки\n"
    "• /export — экспорт базы\n"
    "• /mcp — конфиг для MCP-сервера\n"
    "Кидай в канал что угодно — я индексирую. Ищи прямо здесь, в DM."
)


KEEP_MARKERS = {".", "keep", "оставить", "продолжить"}


def _mask(v: str | None) -> str:
    if not v:
        return ""
    return f"…{v[-4:]}"


def _wants_keep(text: str) -> bool:
    clean = text.strip().lower()
    return clean == "" or clean in KEEP_MARKERS


def prompt_for_step(conn: sqlite3.Connection, owner_id: int, step: str) -> str:
    owner = get_owner(conn, owner_id)
    if not owner:
        return PROMPTS[step]

    if step == "jina" and owner.jina_api_key:
        return (
            "Шаг 1/4 — ключ Jina.\n"
            f"В `.env` уже есть ключ `{_mask(owner.jina_api_key)}`.\n"
            "Отправьте новое значение, чтобы заменить его, или `.` чтобы оставить."
        )
    if step == "deepgram" and owner.deepgram_api_key:
        return (
            "Шаг 2/4 — ключ Deepgram.\n"
            f"В `.env` уже есть ключ `{_mask(owner.deepgram_api_key)}`.\n"
            "Отправьте новое значение, чтобы заменить его, или `.` чтобы оставить."
        )
    if step == "github":
        from src.bot.handlers.setup_github import prompt_for_github_step
        return prompt_for_github_step(owner)
    return PROMPTS[step]


async def process_setup_message(conn: sqlite3.Connection, owner_id: int,
                                 text: str) -> str:
    """Pure logic of the setup wizard. Returns the next prompt to send."""
    owner = get_owner(conn, owner_id)
    step = owner.setup_step or "jina"

    if step == "jina":
        api_key = owner.jina_api_key if _wants_keep(text) else text.strip()
        if not api_key:
            return PROMPTS["jina"]
        client = JinaClient(api_key=api_key)
        if not await client.validate_key():
            return "Ключ Jina не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "jina_api_key", api_key)
        advance_setup_step(conn, owner_id, "deepgram")
        return prompt_for_step(conn, owner_id, "deepgram")

    if step == "deepgram":
        api_key = owner.deepgram_api_key if _wants_keep(text) else text.strip()
        if not api_key:
            return PROMPTS["deepgram"]
        client = DeepgramClient(api_key=api_key)
        if not await client.validate_key():
            return "Ключ Deepgram не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "deepgram_api_key", api_key)
        advance_setup_step(conn, owner_id, "github")
        return prompt_for_step(conn, owner_id, "github")

    if step == "github":
        # Parsed in Task 17 (github step handler)
        from src.bot.handlers.setup_github import handle_github_step
        return await handle_github_step(conn, owner_id, text)

    if step == "channel":
        # Set via forward handler — see Task 18
        return "Жду форвард сообщения из канала «Избранное 2»."

    if step == "done":
        return ""  # ignore — handled by other handlers

    return "Не понимаю. Попробуй /start."


async def setup_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes private text messages into the wizard while it is in progress.
    Search handler ignores anything before setup_step == 'done', so without
    this dispatcher API keys submitted during /start were silently dropped."""
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or owner.setup_step in (None, "done", "channel"):
        return  # search / forward handlers take over

    text = update.message.text or ""

    try:
        reply = await process_setup_message(conn, settings.owner_telegram_id, text)
    except Exception:
        logger.exception("setup wizard step %s crashed", owner.setup_step)
        await update.message.reply_text(
            "Что-то сломалось на этом шаге. Попробуй ещё раз или /cancel."
        )
        return

    if reply:
        await update.message.reply_text(reply, parse_mode="Markdown")


async def forward_inbox_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if owner.setup_step != "channel":
        return  # other handlers (search) take over

    msg = update.message
    if not msg.forward_origin or msg.forward_origin.type != "channel":
        await msg.reply_text(
            "Это не подходит. Мне нужен форвард из **твоего** приватного канала, "
            "а не из чужого.\n\n"
            "Что сделать:\n"
            "1) Открой свой канал (например «Избранное»).\n"
            "2) **Сам напиши** там новое сообщение — «привет», что угодно.\n"
            "3) Долгое нажатие на это сообщение → «Переслать» → выбери этот чат.",
            parse_mode="Markdown",
        )
        return

    chat_id = msg.forward_origin.chat.id
    chat_title = msg.forward_origin.chat.title or str(chat_id)

    # Probe write access before persisting anything. If the bot is not an
    # admin, send_message returns 403 and we stay at step='channel' so the
    # user can fix the rights and forward again — instead of silently
    # locking them into a broken inbox_chat_id.
    try:
        sent = await ctx.bot.send_message(chat_id=chat_id, text="✅ Soroka подключилась.")
    except Exception:
        await msg.reply_text(
            f"Не могу публиковать в канал «{chat_title}» — скорее всего, "
            "я там не админ.\n\n"
            "Что сделать:\n"
            "1) Открой канал → ⋮ → Управление каналом → Администраторы\n"
            "2) Добавь меня администратором\n"
            "3) Дай права: Post Messages, Add Reactions\n"
            "4) Перешли сюда любое сообщение из канала ещё раз"
        )
        return

    update_owner_field(conn, settings.owner_telegram_id, "inbox_chat_id", chat_id)
    advance_setup_step(conn, settings.owner_telegram_id, "done")

    ctx.job_queue.run_once(
        lambda c: c.bot.delete_message(chat_id, sent.message_id),
        when=10,
    )
    await msg.reply_text(DONE_MESSAGE)


@owner_only
async def skip_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if owner and owner.setup_step == "github":
        from src.bot.handlers.setup_github import handle_skip_github
        msg = await handle_skip_github(conn, settings.owner_telegram_id)
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Сейчас нечего пропускать.")


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    msg = update.effective_message

    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        await msg.reply_text("Бот настроен на одного владельца.")
        return

    create_or_get_owner(conn, telegram_id=settings.owner_telegram_id)
    owner = get_owner(conn, settings.owner_telegram_id)

    if owner.setup_step == "done":
        await msg.reply_text(DONE_MESSAGE)
        return

    if owner.setup_step is None:
        advance_setup_step(conn, settings.owner_telegram_id, "jina")
        owner = get_owner(conn, settings.owner_telegram_id)

    await msg.reply_text(
        "Привет! Я Soroka. Настроим за 5 минут.\n\n"
        + prompt_for_step(conn, settings.owner_telegram_id, owner.setup_step)
    )


def register_setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("skip", skip_handler))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.FORWARDED,
        forward_inbox_handler,
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.FORWARDED & ~filters.COMMAND,
        setup_text_handler,
    ))
