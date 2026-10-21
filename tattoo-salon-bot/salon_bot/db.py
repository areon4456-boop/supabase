"""SQLite storage. Dates are stored as ISO strings, money as integer kopecks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import aiosqlite

from .payments import Planned

SCHEMA = """
CREATE TABLE IF NOT EXISTS masters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    telegram_id INTEGER UNIQUE,
    invite_code TEXT UNIQUE,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS shifts (
    master_id INTEGER NOT NULL REFERENCES masters(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    PRIMARY KEY (master_id, day)
);
CREATE TABLE IF NOT EXISTS days_off (
    master_id INTEGER NOT NULL REFERENCES masters(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (master_id, day)
);
CREATE TABLE IF NOT EXISTS planned (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    amount INTEGER NOT NULL,
    period TEXT NOT NULL CHECK (period IN ('monthly', 'weekly', 'once')),
    day INTEGER,
    once_day TEXT,
    start_day TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    category TEXT NOT NULL,
    amount INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    planned_id INTEGER REFERENCES planned(id) ON DELETE SET NULL,
    due_day TEXT,
    created_by INTEGER
);
CREATE INDEX IF NOT EXISTS expenses_day ON expenses(day);
CREATE UNIQUE INDEX IF NOT EXISTS expenses_planned_due
    ON expenses(planned_id, due_day) WHERE planned_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "open_weekdays": "0,1,2,3,4,5,6",
    "day_start": "11:00",
    "day_end": "21:00",
    "per_day": "2",
    "max_streak": "5",
    "reminder_time": "10:00",
    "reminders_on": "1",
    "last_reminder_day": "",
    "admins": "",
}


@dataclass(frozen=True)
class Settings:
    open_weekdays: set[int]
    day_start: str
    day_end: str
    per_day: int
    max_streak: int
    reminder_time: str
    reminders_on: bool
    last_reminder_day: str


@dataclass(frozen=True)
class Master:
    id: int
    name: str
    telegram_id: int | None
    active: bool


@dataclass(frozen=True)
class Shift:
    master_id: int
    master_name: str
    day: date
    start: str
    end: str


@dataclass(frozen=True)
class DayOff:
    master_id: int
    master_name: str
    day: date


@dataclass(frozen=True)
class Expense:
    id: int
    day: date
    category: str
    amount: int
    comment: str
    planned_id: int | None
    due_day: date | None


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None
        # Handlers run concurrently on one connection: serialize writes so one handler's
        # commit never lands in the middle of another's multi-statement transaction.
        self._write_lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", DEFAULT_SETTINGS.items()
        )
        await self._conn.commit()

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._write_lock:
            try:
                yield self.conn
            except BaseException:
                await self.conn.rollback()
                raise
            await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # --- settings -------------------------------------------------------------------------

    async def get_setting(self, key: str) -> str:
        async with self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else DEFAULT_SETTINGS.get(key, "")

    async def set_setting(self, key: str, value: str) -> None:
        async with self._tx() as conn:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    async def get_settings(self) -> Settings:
        async with self.conn.execute("SELECT key, value FROM settings") as cur:
            raw = {**DEFAULT_SETTINGS, **{row["key"]: row["value"] for row in await cur.fetchall()}}
        return Settings(
            open_weekdays={int(x) for x in raw["open_weekdays"].split(",") if x != ""},
            day_start=raw["day_start"],
            day_end=raw["day_end"],
            per_day=int(raw["per_day"]),
            max_streak=int(raw["max_streak"]),
            reminder_time=raw["reminder_time"],
            reminders_on=raw["reminders_on"] == "1",
            last_reminder_day=raw["last_reminder_day"],
        )

    async def db_admins(self) -> set[int]:
        raw = await self.get_setting("admins")
        return {int(x) for x in raw.split(",") if x}

    async def add_db_admin(self, telegram_id: int) -> None:
        admins = await self.db_admins() | {telegram_id}
        await self.set_setting("admins", ",".join(str(a) for a in sorted(admins)))

    # --- masters --------------------------------------------------------------------------

    @staticmethod
    def _master(row: aiosqlite.Row) -> Master:
        return Master(row["id"], row["name"], row["telegram_id"], bool(row["active"]))

    async def add_master(self, name: str) -> int:
        async with self._tx() as conn:
            cur = await conn.execute("INSERT INTO masters (name) VALUES (?)", (name,))
        return cur.lastrowid

    async def list_masters(self) -> list[Master]:
        async with self.conn.execute("SELECT * FROM masters WHERE active = 1 ORDER BY id") as cur:
            return [self._master(r) for r in await cur.fetchall()]

    async def get_master(self, master_id: int) -> Master | None:
        async with self.conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)) as cur:
            row = await cur.fetchone()
        return self._master(row) if row else None

    async def master_by_telegram(self, telegram_id: int) -> Master | None:
        async with self.conn.execute(
            "SELECT * FROM masters WHERE telegram_id = ? AND active = 1", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._master(row) if row else None

    async def rename_master(self, master_id: int, name: str) -> None:
        async with self._tx() as conn:
            await conn.execute("UPDATE masters SET name = ? WHERE id = ?", (name, master_id))

    async def deactivate_master(self, master_id: int, today: date) -> None:
        """Hide the master but keep past shifts for history; future shifts and days off are removed."""
        async with self._tx() as conn:
            await conn.execute(
                "UPDATE masters SET active = 0, telegram_id = NULL, invite_code = NULL WHERE id = ?",
                (master_id,),
            )
            await conn.execute(
                "DELETE FROM shifts WHERE master_id = ? AND day >= ?", (master_id, today.isoformat())
            )
            await conn.execute(
                "DELETE FROM days_off WHERE master_id = ? AND day >= ?", (master_id, today.isoformat())
            )

    async def set_invite_code(self, master_id: int, code: str) -> None:
        async with self._tx() as conn:
            await conn.execute("UPDATE masters SET invite_code = ? WHERE id = ?", (code, master_id))

    async def link_by_invite(self, code: str, telegram_id: int) -> Master | None:
        async with self._tx() as conn:
            async with conn.execute(
                "SELECT id FROM masters WHERE invite_code = ? AND active = 1", (code,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            await conn.execute("UPDATE masters SET telegram_id = NULL WHERE telegram_id = ?", (telegram_id,))
            await conn.execute(
                "UPDATE masters SET telegram_id = ?, invite_code = NULL WHERE id = ?", (telegram_id, row["id"])
            )
        return await self.get_master(row["id"])

    async def unlink_telegram(self, master_id: int) -> None:
        async with self._tx() as conn:
            await conn.execute("UPDATE masters SET telegram_id = NULL WHERE id = ?", (master_id,))

    # --- shifts ---------------------------------------------------------------------------

    async def shifts_between(self, start: date, end: date, master_id: int | None = None) -> list[Shift]:
        sql = (
            "SELECT s.master_id, m.name, s.day, s.start_time, s.end_time FROM shifts s "
            "JOIN masters m ON m.id = s.master_id WHERE s.day BETWEEN ? AND ?"
        )
        params: list[object] = [start.isoformat(), end.isoformat()]
        if master_id is not None:
            sql += " AND s.master_id = ?"
            params.append(master_id)
        sql += " ORDER BY s.day, s.start_time, m.id"
        async with self.conn.execute(sql, params) as cur:
            return [
                Shift(r["master_id"], r["name"], date.fromisoformat(r["day"]), r["start_time"], r["end_time"])
                for r in await cur.fetchall()
            ]

    async def set_shift(self, master_id: int, day: date, start: str, end: str) -> None:
        async with self._tx() as conn:
            await conn.execute(
                "INSERT INTO shifts (master_id, day, start_time, end_time) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(master_id, day) DO UPDATE SET start_time = excluded.start_time, "
                "end_time = excluded.end_time",
                (master_id, day.isoformat(), start, end),
            )

    async def delete_shift(self, master_id: int, day: date) -> None:
        async with self._tx() as conn:
            await conn.execute(
                "DELETE FROM shifts WHERE master_id = ? AND day = ?", (master_id, day.isoformat())
            )

    async def replace_shifts(
        self, start: date, end: date, items: Iterable[tuple[int, date, str, str]]
    ) -> None:
        """Atomically replace every shift in [start, end] with `items`."""
        async with self._tx() as conn:
            await conn.execute(
                "DELETE FROM shifts WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat())
            )
            await conn.executemany(
                "INSERT INTO shifts (master_id, day, start_time, end_time) VALUES (?, ?, ?, ?)",
                [(m, d.isoformat(), s, e) for m, d, s, e in items],
            )

    # --- days off -------------------------------------------------------------------------

    async def add_days_off(self, master_id: int, days: Iterable[date]) -> None:
        async with self._tx() as conn:
            await conn.executemany(
                "INSERT OR IGNORE INTO days_off (master_id, day) VALUES (?, ?)",
                [(master_id, d.isoformat()) for d in days],
            )

    async def delete_day_off(self, master_id: int, day: date) -> None:
        async with self._tx() as conn:
            await conn.execute(
                "DELETE FROM days_off WHERE master_id = ? AND day = ?", (master_id, day.isoformat())
            )

    async def days_off_between(self, start: date, end: date) -> list[DayOff]:
        async with self.conn.execute(
            "SELECT d.master_id, m.name, d.day FROM days_off d JOIN masters m ON m.id = d.master_id "
            "WHERE m.active = 1 AND d.day BETWEEN ? AND ? ORDER BY d.day, m.id",
            (start.isoformat(), end.isoformat()),
        ) as cur:
            return [
                DayOff(r["master_id"], r["name"], date.fromisoformat(r["day"])) for r in await cur.fetchall()
            ]

    # --- expenses -------------------------------------------------------------------------

    @staticmethod
    def _expense(row: aiosqlite.Row) -> Expense:
        return Expense(
            row["id"],
            date.fromisoformat(row["day"]),
            row["category"],
            row["amount"],
            row["comment"],
            row["planned_id"],
            _d(row["due_day"]),
        )

    async def add_expense(
        self,
        day: date,
        category: str,
        amount: int,
        comment: str = "",
        created_by: int | None = None,
        planned_id: int | None = None,
        due_day: date | None = None,
    ) -> int:
        async with self._tx() as conn:
            cur = await conn.execute(
                "INSERT INTO expenses (day, category, amount, comment, created_by, planned_id, due_day) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    day.isoformat(),
                    category,
                    amount,
                    comment,
                    created_by,
                    planned_id,
                    due_day.isoformat() if due_day else None,
                ),
            )
        return cur.lastrowid

    async def get_expense(self, expense_id: int) -> Expense | None:
        async with self.conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)) as cur:
            row = await cur.fetchone()
        return self._expense(row) if row else None

    async def delete_expense(self, expense_id: int) -> bool:
        async with self._tx() as conn:
            cur = await conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return cur.rowcount > 0

    async def expenses_between(self, start: date, end: date) -> list[Expense]:
        async with self.conn.execute(
            "SELECT * FROM expenses WHERE day BETWEEN ? AND ? ORDER BY day, id",
            (start.isoformat(), end.isoformat()),
        ) as cur:
            return [self._expense(r) for r in await cur.fetchall()]

    async def recent_expenses(self, limit: int = 10) -> list[Expense]:
        async with self.conn.execute(
            "SELECT * FROM expenses ORDER BY day DESC, id DESC LIMIT ?", (limit,)
        ) as cur:
            return [self._expense(r) for r in await cur.fetchall()]

    async def total_between(self, start: date, end: date) -> int:
        async with self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ) as cur:
            row = await cur.fetchone()
        return row["total"]

    async def paid_occurrences(self, start: date, end: date) -> set[tuple[int, date]]:
        async with self.conn.execute(
            "SELECT planned_id, due_day FROM expenses "
            "WHERE planned_id IS NOT NULL AND due_day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ) as cur:
            return {(r["planned_id"], date.fromisoformat(r["due_day"])) for r in await cur.fetchall()}

    # --- planned payments -----------------------------------------------------------------

    @staticmethod
    def _planned(row: aiosqlite.Row) -> Planned:
        return Planned(
            id=row["id"],
            title=row["title"],
            category=row["category"],
            amount=row["amount"],
            period=row["period"],
            day=row["day"],
            once_day=_d(row["once_day"]),
            start_day=date.fromisoformat(row["start_day"]),
        )

    async def add_planned(
        self,
        title: str,
        category: str,
        amount: int,
        period: str,
        day: int | None,
        once_day: date | None,
        start_day: date,
    ) -> int:
        async with self._tx() as conn:
            cur = await conn.execute(
                "INSERT INTO planned (title, category, amount, period, day, once_day, start_day) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    category,
                    amount,
                    period,
                    day,
                    once_day.isoformat() if once_day else None,
                    start_day.isoformat(),
                ),
            )
        return cur.lastrowid

    async def list_planned(self) -> list[Planned]:
        async with self.conn.execute("SELECT * FROM planned WHERE active = 1 ORDER BY id") as cur:
            return [self._planned(r) for r in await cur.fetchall()]

    async def get_planned(self, planned_id: int) -> Planned | None:
        async with self.conn.execute(
            "SELECT * FROM planned WHERE id = ? AND active = 1", (planned_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._planned(row) if row else None

    async def deactivate_planned(self, planned_id: int) -> None:
        async with self._tx() as conn:
            await conn.execute("UPDATE planned SET active = 0 WHERE id = ?", (planned_id,))
