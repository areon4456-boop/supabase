"""Planned (recurring) payments: when each one falls due."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .fmt import WEEKDAYS_EVERY, fmt_date


@dataclass(frozen=True)
class Planned:
    id: int
    title: str
    category: str
    amount: int  # kopecks
    period: str  # "monthly" | "weekly" | "once"
    day: int | None  # day of month (monthly) or weekday 0-6 (weekly)
    once_day: date | None
    start_day: date

    def describe(self) -> str:
        if self.period == "monthly":
            return f"ежемесячно, {self.day}-го числа"
        if self.period == "weekly":
            return WEEKDAYS_EVERY[self.day or 0]
        return f"разово, {fmt_date(self.once_day)}" if self.once_day else "разово"


@dataclass(frozen=True)
class Occurrence:
    planned: Planned
    due: date
    paid: bool


def occurrences(p: Planned, start: date, end: date) -> list[date]:
    """Due dates of `p` within [start, end]. Monthly payments on the 31st fall on the last day of short months."""
    if p.period == "once":
        return [p.once_day] if p.once_day and start <= p.once_day <= end else []

    first = max(start, p.start_day)
    if first > end:
        return []

    if p.period == "weekly":
        due = first + timedelta(days=((p.day or 0) - first.weekday()) % 7)
        result = []
        while due <= end:
            result.append(due)
            due += timedelta(days=7)
        return result

    result = []
    year, month = first.year, first.month
    while (year, month) <= (end.year, end.month):
        last = calendar.monthrange(year, month)[1]
        due = date(year, month, min(p.day or 1, last))
        if first <= due <= end:
            result.append(due)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def schedule(
    plans: list[Planned], start: date, end: date, paid: set[tuple[int, date]]
) -> list[Occurrence]:
    items = [
        Occurrence(planned=p, due=due, paid=(p.id, due) in paid)
        for p in plans
        for due in occurrences(p, start, end)
    ]
    return sorted(items, key=lambda o: (o.due, o.planned.title))
