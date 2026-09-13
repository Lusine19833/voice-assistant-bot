"""Распознавание голосовых сообщений (speech-to-text) через OpenAI Audio API.

Отдельный провайдер от Claude, потому что Anthropic API пока не принимает
аудио на вход — только текст и изображения. Whisper (whisper-1) хорошо
работает с русской речью и напрямую понимает ogg/opus — конвертация формата
не нужна, файл из Telegram передаётся как есть.
"""
import logging
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class SpeechToText:
    def __init__(self, api_key: str, model: str = "whisper-1", language: str = "ru"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.language = language

    async def transcribe(self, audio_path: Path) -> str:
        with open(audio_path, "rb") as audio_file:
            transcript = await self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language=self.language,
            )
        return transcript.text.strip()
