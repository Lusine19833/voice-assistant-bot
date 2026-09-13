"""Обёртка над Claude: обычный диалог + распознавание намерения поставить напоминание."""
import json
import logging
from datetime import datetime

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """Ты — личный голосовой ассистент пользователя в Telegram.
Отвечай по-русски, кратко, по-разговорному и по делу.
Твой ответ может быть озвучен вслух, поэтому:
- не используй markdown-разметку, списки с маркерами, таблицы или заголовки;
- избегай длинных абзацев — 2-4 предложения на ответ, если не попросили подробнее;
- пиши так, как будто отвечаешь другу голосом, а не пишешь документ.
Если пользователь просит напомнить о чём-то — просто подтверди обычной фразой
("хорошо, напомню"), отдельная система уже создаст напоминание."""

REMINDER_SYSTEM_PROMPT = """Ты извлекаешь из одной реплики пользователя намерение поставить напоминание.
Текущее время: {now}
Часовой пояс пользователя: {tz}

Верни ТОЛЬКО JSON без пояснений и без markdown-разметки, строго в таком виде:
{{"is_reminder": true|false, "when_iso": "ISO8601 datetime со смещением часового пояса или null", "text": "о чём напомнить, короткой фразой"}}

Правила:
- is_reminder=true только если пользователь явно просит напомнить/не забыть что-то сделать в конкретное время или через промежуток времени.
- when_iso обязателен, если is_reminder=true — переведи относительное время ("через час", "завтра в 9", "в понедельник вечером") в конкретную дату и время относительно текущего времени.
- Если время не удалось однозначно определить — is_reminder=false.
- Если сообщение — это обычный вопрос или разговор, не про напоминание — is_reminder=false, when_iso=null, text="".
"""


class Assistant:
    def __init__(self, api_key: str, model: str):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def reply(self, history: list[dict]) -> str:
        """history — список {"role": "user"/"assistant", "content": "..."} в хронологическом порядке."""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=600,
            system=CHAT_SYSTEM_PROMPT,
            messages=history,
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()

    async def parse_reminder(self, text: str, now: datetime, tz: str) -> dict:
        prompt = REMINDER_SYSTEM_PROMPT.format(now=now.isoformat(), tz=tz)
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = "".join(block.text for block in response.content if block.type == "text").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Не удалось распарсить JSON напоминания: %r", raw)
            return {"is_reminder": False, "when_iso": None, "text": ""}

        if not isinstance(data, dict) or "is_reminder" not in data:
            return {"is_reminder": False, "when_iso": None, "text": ""}
        return data
