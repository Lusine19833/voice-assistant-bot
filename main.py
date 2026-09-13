"""Точка входа: Telegram-бот, объединяющий Claude, напоминания и озвучку ответов."""
import asyncio
import logging
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from bot.assistant import Assistant
from bot.config import load_config
from bot.reminders import Reminder, ReminderScheduler, ReminderStore
from bot.tts import synthesize_voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("voice-assistant")

MAX_HISTORY_MESSAGES = 20  # последние ~10 обменов репликами, чтобы не раздувать контекст

# История диалога в памяти процесса: chat_id -> [{"role": ..., "content": ...}, ...]
_history: dict[int, list[dict]] = {}


def _is_allowed(config, user_id: int) -> bool:
    return config.allowed_user_id is None or user_id == config.allowed_user_id


def _push_history(chat_id: int, role: str, content: str) -> None:
    history = _history.setdefault(chat_id, [])
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY_MESSAGES:
        del history[: len(history) - MAX_HISTORY_MESSAGES]


async def _send_reply(bot: Bot, chat_id: int, text: str, tts_voice: str) -> None:
    """Отправляет ответ текстом и следом — голосовым сообщением."""
    await bot.send_message(chat_id, text)
    try:
        ogg_path = await synthesize_voice(text, tts_voice)
    except Exception:
        logger.exception("Не удалось синтезировать речь, отправляю только текст")
        return
    try:
        await bot.send_voice(chat_id, voice=FSInputFile(ogg_path))
    finally:
        shutil.rmtree(ogg_path.parent, ignore_errors=True)


def build_dispatcher(config, assistant: Assistant, store: ReminderStore,
                      scheduler: ReminderScheduler) -> Dispatcher:
    dp = Dispatcher()
    tz = ZoneInfo(config.timezone)

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not _is_allowed(config, message.from_user.id):
            await message.answer("Этот бот настроен как личный ассистент другого пользователя.")
            return
        await message.answer(
            "Привет! Я твой личный ассистент. Пиши мне что угодно — отвечу текстом и голосом.\n"
            "Попроси напомнить о чём-то («напомни завтра в 9 позвонить маме») — поставлю напоминание.\n"
            "/list — показать активные напоминания\n"
            "/cancel <номер> — отменить напоминание"
        )

    @dp.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        if not _is_allowed(config, message.from_user.id):
            return
        pending = await store.list_pending(chat_id=message.chat.id)
        if not pending:
            await message.answer("Активных напоминаний нет.")
            return
        lines = [
            f"#{r.id} — {r.when_at.strftime('%d.%m %H:%M')} — {r.text}"
            for r in pending
        ]
        await message.answer("\n".join(lines))

    @dp.message(Command("cancel"))
    async def cmd_cancel(message: Message) -> None:
        if not _is_allowed(config, message.from_user.id):
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip().lstrip("#").isdigit():
            await message.answer("Укажи номер напоминания: /cancel 3 (номера показывает /list)")
            return
        reminder_id = int(parts[1].strip().lstrip("#"))
        ok = await store.cancel(reminder_id, message.chat.id)
        if ok:
            scheduler.cancel_job(reminder_id)
            await message.answer(f"Напоминание #{reminder_id} отменено.")
        else:
            await message.answer("Не нашёл такое напоминание среди активных.")

    @dp.message(F.voice)
    async def handle_voice(message: Message) -> None:
        if not _is_allowed(config, message.from_user.id):
            return
        await message.answer(
            "Пока умею понимать только текст — распознавание голосовых сообщений "
            "в эту версию не добавлено. Продиктуй через клавиатуру голосовым вводом "
            "телефона, я отвечу текстом и голосом."
        )

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        if not _is_allowed(config, message.from_user.id):
            await message.answer("Этот бот настроен как личный ассистент другого пользователя.")
            return

        chat_id = message.chat.id
        text = message.text

        now = datetime.now(tz)
        reminder_data = await assistant.parse_reminder(text, now, config.timezone)

        if reminder_data.get("is_reminder") and reminder_data.get("when_iso"):
            try:
                when_at = datetime.fromisoformat(reminder_data["when_iso"])
                if when_at.tzinfo is None:
                    when_at = when_at.replace(tzinfo=tz)
            except ValueError:
                when_at = None

            if when_at is not None:
                reminder_id = await store.add(chat_id, reminder_data["text"], when_at)
                scheduler.schedule_new(Reminder(reminder_id, chat_id, reminder_data["text"], when_at))
                confirmation = (
                    f"Хорошо, напомню {when_at.strftime('%d.%m в %H:%M')}: {reminder_data['text']}"
                )
                _push_history(chat_id, "user", text)
                _push_history(chat_id, "assistant", confirmation)
                await _send_reply(message.bot, chat_id, confirmation, config.tts_voice)
                return

        # Обычный разговорный ответ
        _push_history(chat_id, "user", text)
        try:
            reply_text = await assistant.reply(_history[chat_id])
        except Exception:
            logger.exception("Ошибка при обращении к Claude")
            await message.answer("Что-то пошло не так на моей стороне, попробуй ещё раз через минуту.")
            return
        _push_history(chat_id, "assistant", reply_text)
        await _send_reply(message.bot, chat_id, reply_text, config.tts_voice)

    return dp


async def _on_reminder_fire(bot: Bot, tts_voice: str, reminder: Reminder) -> None:
    text = f"Напоминаю: {reminder.text}"
    await _send_reply(bot, reminder.chat_id, text, tts_voice)


async def main() -> None:
    config = load_config()
    bot = Bot(token=config.telegram_token)
    assistant = Assistant(config.anthropic_api_key, config.claude_model)
    store = ReminderStore(config.db_path)
    await store.init()

    scheduler = ReminderScheduler(store, on_fire=lambda r: _on_reminder_fire(bot, config.tts_voice, r))
    await scheduler.start()

    dp = build_dispatcher(config, assistant, store, scheduler)

    logger.info("Бот запущен, модель Claude: %s, голос: %s", config.claude_model, config.tts_voice)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
