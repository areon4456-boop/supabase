"""Automatic shift planning: spread open days evenly across masters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date


@dataclass
class PlanResult:
    assignments: dict[date, list[int]]
    # Open days where fewer than `per_day` masters could be scheduled -> how many are missing.
    shortages: dict[date, int]
    counts: dict[int, int]


def plan_shifts(
    days: Iterable[date],
    masters: list[int],
    open_weekdays: set[int],
    per_day: int,
    max_streak: int,
    days_off: Mapping[int, set[date]] | None = None,
    initial_streak: Mapping[int, int] | None = None,
) -> PlanResult:
    """Greedy, fair planner.

    For every open day it picks `per_day` available masters with the fewest shifts so far
    (weekend shifts are balanced separately), never more than `max_streak` days in a row
    and never on a requested day off. Ties rotate so nobody is always first in line.
    `initial_streak` carries consecutive days already worked right before the period.
    """
    days_off = days_off or {}
    initial_streak = initial_streak or {}
    order = {m: i for i, m in enumerate(masters)}
    streak = {m: initial_streak.get(m, 0) for m in masters}
    counts = {m: 0 for m in masters}
    weekend_counts = {m: 0 for m in masters}
    assignments: dict[date, list[int]] = {}
    shortages: dict[date, int] = {}

    for index, day in enumerate(sorted(days)):
        if day.weekday() not in open_weekdays:
            for m in masters:
                streak[m] = 0
            continue

        is_weekend = day.weekday() >= 5
        available = [m for m in masters if day not in days_off.get(m, ()) and streak[m] < max_streak]

        ranked = sorted(
            available,
            key=lambda m: (
                counts[m],
                weekend_counts[m] if is_weekend else 0,
                (order[m] - index) % len(masters),  # rotate ties
            ),
        )
        chosen = set(ranked[:per_day])
        for m in masters:
            if m in chosen:
                streak[m] += 1
                counts[m] += 1
                weekend_counts[m] += is_weekend
            else:
                streak[m] = 0

        assignments[day] = [m for m in masters if m in chosen]
        if len(chosen) < per_day:
            shortages[day] = per_day - len(chosen)

    return PlanResult(assignments=assignments, shortages=shortages, counts=counts)
