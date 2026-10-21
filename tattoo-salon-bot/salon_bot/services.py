"""Use cases that combine storage with the pure planning/payment logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .db import Database, Master, Settings
from .fmt import days_between, month_bounds, shift_month
from .payments import Occurrence, schedule
from .planner import PlanResult, plan_shifts


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


@dataclass
class Generation:
    start: date
    end: date
    result: PlanResult
    masters: list[Master]
    settings: Settings


def generation_period(year: int, month: int, today: date) -> tuple[date, date] | None:
    """The part of the month that can still be (re)planned: from today on."""
    first, last = month_bounds(year, month)
    start = max(first, today)
    return None if start > last else (start, last)


async def generate_month(db: Database, year: int, month: int, today: date) -> Generation | None:
    period = generation_period(year, month, today)
    if period is None:
        return None
    start, end = period
    settings = await db.get_settings()
    masters = await db.list_masters()

    days_off: dict[int, set[date]] = {}
    for o in await db.days_off_between(start, end):
        days_off.setdefault(o.master_id, set()).add(o.day)

    # Respect the "days in a row" limit across the boundary with already planned days.
    lookback = await db.shifts_between(start - timedelta(days=settings.max_streak), start - timedelta(days=1))
    worked = {(s.master_id, s.day) for s in lookback}
    initial_streak = {}
    for m in masters:
        streak, day = 0, start - timedelta(days=1)
        while (m.id, day) in worked:
            streak += 1
            day -= timedelta(days=1)
        initial_streak[m.id] = streak

    result = plan_shifts(
        days=days_between(start, end),
        masters=[m.id for m in masters],
        open_weekdays=settings.open_weekdays,
        per_day=settings.per_day,
        max_streak=settings.max_streak,
        days_off=days_off,
        initial_streak=initial_streak,
    )
    await db.replace_shifts(
        start,
        end,
        [
            (master_id, day, settings.day_start, settings.day_end)
            for day, master_ids in result.assignments.items()
            for master_id in master_ids
        ],
    )
    return Generation(start=start, end=end, result=result, masters=masters, settings=settings)


async def payment_plan(db: Database, start: date, end: date) -> list[Occurrence]:
    plans = await db.list_planned()
    paid = await db.paid_occurrences(start, end)
    return schedule(plans, start, end, paid)


async def month_payment_plan(db: Database, year: int, month: int) -> list[Occurrence]:
    return await payment_plan(db, *month_bounds(year, month))


async def monthly_totals(db: Database, year: int, month: int, months: int = 6) -> list[tuple[int, int, int]]:
    """(year, month, total kopecks) for `months` months ending with the given one."""
    result = []
    for delta in range(-(months - 1), 1):
        y, m = shift_month(year, month, delta)
        result.append((y, m, await db.total_between(*month_bounds(y, m))))
    return result


async def due_soon(db: Database, today: date, days_ahead: int = 3) -> list[Occurrence]:
    """Unpaid payments that are overdue (since the start of last month) or due within `days_ahead` days."""
    y, m = shift_month(today.year, today.month, -1)
    start = date(y, m, 1)
    plan = await payment_plan(db, start, today + timedelta(days=days_ahead))
    return [o for o in plan if not o.paid]
