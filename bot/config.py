"""Загрузка конфигурации из переменных окружения (.env для локального запуска)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Переменная окружения {name} не задана. "
            f"Скопируйте .env.example в .env и заполните значения."
        )
    return value


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_api_key: str
    allowed_user_id: int | None
    timezone: str
    claude_model: str
    tts_voice: str
    db_path: str
    openai_api_key: str | None
    stt_model: str
    stt_language: str


def load_config() -> Config:
    allowed_user_raw = os.getenv("ALLOWED_USER_ID", "").strip()
    return Config(
        telegram_token=_require("TELEGRAM_BOT_TOKEN"),
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        allowed_user_id=int(allowed_user_raw) if allowed_user_raw else None,
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5"),
        tts_voice=os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural"),
        db_path=os.getenv("DB_PATH", "assistant.sqlite3"),
        # Ключ для распознавания голосовых сообщений (OpenAI Whisper).
        # Не задан — бот просто попросит написать текстом вместо голосового.
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        stt_model=os.getenv("STT_MODEL", "whisper-1"),
        stt_language=os.getenv("STT_LANGUAGE", "ru"),
    )
