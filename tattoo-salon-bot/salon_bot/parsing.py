"""Parsing of free-form user input: dates, date lists, amounts, hours."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

Prefer = Literal["future", "past"] | None

_WORD_DAYS = {"позавчера": -2, "вчера": -1, "сегодня": 0, "завтра": 1, "послезавтра": 2}
_DOT_DATE = re.compile(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}|\d{2}))?$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_AMOUNT = re.compile(
    r"^(?P<int>\d{1,3}(?:[   ]\d{3})+(?!\d)|\d+)"
    r"(?:[.,](?P<frac>\d{1,2})(?!\d))?"
    r"(?:\s*(?P<k>к|k|тыс\.?)(?![а-яёa-z]))?"
    r"\s*(?:₽|руб\.?|р\.)?",
    re.IGNORECASE,
)
_TIME_RANGE = re.compile(
    r"^(?:с\s*)?(\d{1,2})(?:[:.](\d{2}))?\s*(?:-|–|—|до)\s*(\d{1,2})(?:[:.](\d{2}))?$",
    re.IGNORECASE,
)
_TIME = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?$")

MAX_AMOUNT_KOPECKS = 100_000_000 * 100
MAX_RANGE_DAYS = 62


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str, today: date, prefer: Prefer = None) -> date | None:
    """Parse "сегодня", "21.10", "21.10.26", "21/10/2026" or "2026-10-21".

    Without a year, `prefer` decides which side of today an ambiguous date lands on:
    "future" moves dates more than a month in the past to next year (for planning),
    "past" moves dates more than a month ahead to last year (for logging expenses).
    """
    s = text.strip().lower().rstrip(".")
    if s in _WORD_DAYS:
        return today + timedelta(days=_WORD_DAYS[s])
    if m := _ISO_DATE.match(s):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    m = _DOT_DATE.match(s)
    if not m:
        return None
    day, month, year_raw = int(m[1]), int(m[2]), m[3]
    if year_raw:
        year = int(year_raw) + (2000 if len(year_raw) == 2 else 0)
        return _safe_date(year, month, day)
    result = _safe_date(today.year, month, day)
    if result is None:
        # 29.02 in a non-leap year: try the neighbouring year the caller prefers.
        shift = -1 if prefer == "past" else 1
        return _safe_date(today.year + shift, month, day)
    if prefer == "future" and result < today - timedelta(days=31):
        return _safe_date(today.year + 1, month, day)
    if prefer == "past" and result > today + timedelta(days=31):
        return _safe_date(today.year - 1, month, day)
    return result


def parse_dates(text: str, today: date, prefer: Prefer = "future") -> list[date] | None:
    """Parse a list like "25.10, 27.10-29.10 завтра". Returns None if anything is invalid."""
    normalized = re.sub(r"\s*[–—-]\s*", "-", text.strip().lower())
    tokens = [t for t in re.split(r"[,;\s]+", normalized) if t]
    if not tokens:
        return None
    result: set[date] = set()
    for token in tokens:
        single = parse_date(token, today, prefer)
        if single:
            result.add(single)
            continue
        parts = token.split("-")
        if len(parts) != 2:
            return None
        start, end = parse_date(parts[0], today, prefer), parse_date(parts[1], today, prefer)
        if not start or not end:
            return None
        if end < start:
            # "28.12-03.01": the end belongs to the next year.
            end = _safe_date(end.year + 1, end.month, end.day)
            if end is None:
                return None
        if (end - start).days > MAX_RANGE_DAYS:
            return None
        result.update(start + timedelta(days=i) for i in range((end - start).days + 1))
    return sorted(result)


def _match_amount(text: str) -> tuple[int, str] | None:
    m = _AMOUNT.match(text)
    if not m:
        return None
    integer = int(re.sub(r"\D", "", m["int"]))
    frac = int((m["frac"] or "0").ljust(2, "0"))
    kopecks = integer * 100 + frac
    if m["k"]:
        kopecks *= 1000
    if not 0 < kopecks <= MAX_AMOUNT_KOPECKS:
        return None
    return kopecks, text[m.end():]


def parse_amount(text: str) -> int | None:
    """Parse "3500", "3 500", "3500,50", "3.5к" into kopecks."""
    matched = _match_amount(text.strip())
    if not matched or matched[1].strip():
        return None
    return matched[0]


def parse_expense(text: str, today: date) -> tuple[date, int, str] | None:
    """Parse "[дата] сумма [комментарий]", e.g. "вчера 3 500 краска Dynamic"."""
    text = text.strip()
    first, _, tail = text.partition(" ")
    parsed_day = parse_date(first, today, prefer="past")
    # "3.5 краска" also looks like a date (3 May), so fall back to reading it as an amount.
    attempts = [(parsed_day, tail.strip())] if parsed_day else []
    attempts.append((today, text))
    for day, rest in attempts:
        matched = _match_amount(rest)
        if matched:
            kopecks, comment = matched
            return day, kopecks, comment.strip(" -—–,.")
    return None


def parse_time_range(text: str) -> tuple[str, str] | None:
    """Parse "11-21", "11:00–21:00", "с 10 до 19:30" into ("HH:MM", "HH:MM")."""
    m = _TIME_RANGE.match(text.strip())
    if not m:
        return None
    start = _to_time(m[1], m[2])
    end = _to_time(m[3], m[4])
    if not start or not end or end <= start:
        return None
    return start, end


def parse_time(text: str) -> str | None:
    m = _TIME.match(text.strip())
    return _to_time(m[1], m[2]) if m else None


def _to_time(hours: str, minutes: str | None) -> str | None:
    h, mnt = int(hours), int(minutes or 0)
    if h == 24 and mnt == 0:
        return "24:00"
    if not (0 <= h <= 23 and 0 <= mnt <= 59):
        return None
    return f"{h:02d}:{mnt:02d}"
