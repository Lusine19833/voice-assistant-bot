FROM python:3.11-slim

# ffmpeg нужен pydub/edge-tts для конвертации речи в ogg/opus
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Здесь же будет жить assistant.sqlite3 — на Railway/Render подключите volume
# на /app, чтобы напоминания переживали передеплой (см. README).
CMD ["python", "-m", "bot.main"]
