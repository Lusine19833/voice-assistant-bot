"""Синтез речи в голосовое сообщение Telegram.

Используется edge-tts — бесплатный сервис синтеза речи (голоса Microsoft Edge),
без API-ключа и без ограничений по квоте, с хорошими русскими голосами.
Результат конвертируется в ogg/opus — формат, который Telegram принимает
как голосовое сообщение через send_voice.

Для конвертации нужен установленный в системе ffmpeg (см. Dockerfile).
"""
import asyncio
import logging
import tempfile
from pathlib import Path

import edge_tts
from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Слишком длинный ответ не озвучиваем целиком, чтобы голосовое не превращалось
# в трёхминутную лекцию — текстом пользователь всё равно получит полный ответ.
MAX_TTS_CHARS = 1200


async def synthesize_voice(text: str, voice: str) -> Path:
    """Возвращает путь к временному .ogg (opus) файлу с озвученным текстом.

    Вызывающий код отвечает за удаление временной директории после отправки.
    """
    text = text.strip()[:MAX_TTS_CHARS]
    if not text:
        raise ValueError("Пустой текст нечего озвучивать")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tts_"))
    mp3_path = tmp_dir / "speech.mp3"
    ogg_path = tmp_dir / "speech.ogg"

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(mp3_path))

    await asyncio.to_thread(_convert_to_ogg, mp3_path, ogg_path)
    return ogg_path


def _convert_to_ogg(mp3_path: Path, ogg_path: Path) -> None:
    audio = AudioSegment.from_file(mp3_path, format="mp3")
    audio.export(ogg_path, format="ogg", codec="libopus")
