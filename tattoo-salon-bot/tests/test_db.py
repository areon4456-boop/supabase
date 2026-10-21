import asyncio
import sqlite3
from datetime import date

import pytest

from salon_bot.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "salon.db")
    await database.connect()
    yield database
    await database.close()


async def test_replace_shifts_is_atomic(db):
    anya = await db.add_master("Аня")
    day = date(2026, 11, 2)
    await db.set_shift(anya, day, "11:00", "21:00")
    with pytest.raises(sqlite3.IntegrityError):
        # Unknown master violates the foreign key: nothing may be deleted.
        await db.replace_shifts(day, day, [(999, day, "11:00", "21:00")])
    assert [s.master_id for s in await db.shifts_between(day, day)] == [anya]


async def test_concurrent_writes_do_not_interleave(db):
    masters = [await db.add_master(f"m{i}") for i in range(3)]
    days = [date(2026, 11, d) for d in range(1, 31)]
    items = [(m, d, "11:00", "21:00") for d in days for m in masters]
    await asyncio.gather(
        db.replace_shifts(days[0], days[-1], items),
        *(db.set_setting("reminder_time", f"{h:02d}:00") for h in range(10)),
        db.add_expense(days[0], "rent", 100),
    )
    assert len(await db.shifts_between(days[0], days[-1])) == len(items)
    assert len(await db.recent_expenses()) == 1


async def test_paid_occurrence_is_unique(db):
    planned = await db.add_planned("Аренда", "rent", 100, "monthly", 1, None, date(2026, 1, 1))
    due = date(2026, 11, 1)
    await db.add_expense(due, "rent", 100, planned_id=planned, due_day=due)
    with pytest.raises(sqlite3.IntegrityError):
        await db.add_expense(due, "rent", 100, planned_id=planned, due_day=due)
    assert await db.paid_occurrences(due, due) == {(planned, due)}
