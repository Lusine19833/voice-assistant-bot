"""Хранение напоминаний (SQLite) и их планирование (APScheduler).

Источник истины — таблица в SQLite, поэтому после перезапуска бота
все ещё не сработавшие напоминания подхватываются заново из базы.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    when_at TEXT NOT NULL,
    fired INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


@dataclass
class Reminder:
    id: int
    chat_id: int
    text: str
    when_at: datetime


class ReminderStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(SCHEMA)
            await db.commit()

    async def add(self, chat_id: int, text: str, when_at: datetime) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO reminders (chat_id, text, when_at, fired, created_at) "
                "VALUES (?, ?, ?, 0, ?)",
                (chat_id, text, when_at.isoformat(), datetime.now().astimezone().isoformat()),
            )
            await db.commit()
            return cursor.lastrowid

    async def list_pending(self, chat_id: Optional[int] = None) -> list[Reminder]:
        query = "SELECT id, chat_id, text, when_at FROM reminders WHERE fired = 0"
        params: tuple = ()
        if chat_id is not None:
            query += " AND chat_id = ?"
            params = (chat_id,)
        query += " ORDER BY when_at ASC"
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        return [
            Reminder(id=r[0], chat_id=r[1], text=r[2], when_at=datetime.fromisoformat(r[3]))
            for r in rows
        ]

    async def mark_fired(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
            await db.commit()

    async def cancel(self, reminder_id: int, chat_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE reminders SET fired = 1 WHERE id = ? AND chat_id = ? AND fired = 0",
                (reminder_id, chat_id),
            )
            await db.commit()
            return cursor.rowcount > 0


class ReminderScheduler:
    """Планирует срабатывание напоминаний в памяти процесса.

    При старте перечитывает несработавшие напоминания из ReminderStore —
    это и есть механизм переживания рестарта бота.
    """

    def __init__(self, store: ReminderStore, on_fire: Callable[[Reminder], Awaitable[None]]):
        self.store = store
        self.on_fire = on_fire
        self.scheduler = AsyncIOScheduler()

    async def start(self) -> None:
        self.scheduler.start()
        await self._reschedule_all()

    async def _reschedule_all(self) -> None:
        for reminder in await self.store.list_pending():
            self._schedule_job(reminder)

    def _schedule_job(self, reminder: Reminder) -> None:
        now = datetime.now().astimezone()
        # Если бот был выключен и время уже прошло — напоминание придёт почти сразу,
        # а не потеряется молча.
        run_date = reminder.when_at if reminder.when_at > now else now
        self.scheduler.add_job(
            self._fire,
            trigger=DateTrigger(run_date=run_date),
            args=[reminder],
            id=f"reminder-{reminder.id}",
            replace_existing=True,
        )

    async def _fire(self, reminder: Reminder) -> None:
        try:
            await self.on_fire(reminder)
        except Exception:
            logger.exception("Не удалось отправить напоминание #%s", reminder.id)
        finally:
            await self.store.mark_fired(reminder.id)

    def schedule_new(self, reminder: Reminder) -> None:
        self._schedule_job(reminder)

    def cancel_job(self, reminder_id: int) -> None:
        job_id = f"reminder-{reminder_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
