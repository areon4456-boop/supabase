from datetime import date, timedelta

from salon_bot.fmt import fmt_money, plural
from salon_bot.parsing import parse_amount, parse_date, parse_dates, parse_expense, parse_time_range
from salon_bot.payments import Planned, occurrences, schedule
from salon_bot.planner import plan_shifts

TODAY = date(2026, 10, 21)  # Wednesday


# --- parsing --------------------------------------------------------------------------------


def test_parse_date_forms():
    assert parse_date("сегодня", TODAY) == TODAY
    assert parse_date("Завтра", TODAY) == date(2026, 10, 22)
    assert parse_date("25.10", TODAY) == date(2026, 10, 25)
    assert parse_date("25/10/2027", TODAY) == date(2027, 10, 25)
    assert parse_date("01.02.27", TODAY) == date(2027, 2, 1)
    assert parse_date("2026-12-31", TODAY) == date(2026, 12, 31)
    assert parse_date("31.02", TODAY) is None
    assert parse_date("краска", TODAY) is None


def test_parse_date_year_rollover():
    december = date(2026, 12, 20)
    assert parse_date("05.01", december, prefer="future") == date(2027, 1, 5)
    january = date(2027, 1, 5)
    assert parse_date("28.12", january, prefer="past") == date(2026, 12, 28)


def test_parse_dates_lists_and_ranges():
    assert parse_dates("25.10, 27.10", TODAY) == [date(2026, 10, 25), date(2026, 10, 27)]
    assert parse_dates("30.10 - 02.11", TODAY) == [
        date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)
    ]
    assert parse_dates("30.12–02.01", TODAY) == [
        date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)
    ]
    assert parse_dates("25.10, когда-нибудь", TODAY) is None
    assert parse_dates("01.01.2026-01.12.2026", TODAY) is None  # range too long


def test_parse_amount():
    assert parse_amount("3500") == 350_000
    assert parse_amount("3 500") == 350_000
    assert parse_amount("3500,5") == 350_050
    assert parse_amount("3.5к") == 350_000
    assert parse_amount("60 000 ₽") == 6_000_000
    assert parse_amount("0") is None
    assert parse_amount("много") is None


def test_parse_expense():
    assert parse_expense("3500 краска Dynamic", TODAY) == (TODAY, 350_000, "краска Dynamic")
    assert parse_expense("вчера 1 200 перчатки", TODAY) == (date(2026, 10, 20), 120_000, "перчатки")
    assert parse_expense("05.10 60 000 аренда", TODAY) == (date(2026, 10, 5), 6_000_000, "аренда")
    assert parse_expense("2к иглы", TODAY) == (TODAY, 200_000, "иглы")
    assert parse_expense("300 краска", TODAY) == (TODAY, 30_000, "краска")  # "к" of "краска" is not "thousand"
    assert parse_expense("12.50", TODAY) == (TODAY, 1250, "")  # not a valid date, so an amount
    assert parse_expense("краска", TODAY) is None


def test_parse_time_range():
    assert parse_time_range("11-21") == ("11:00", "21:00")
    assert parse_time_range("с 10:30 до 19") == ("10:30", "19:00")
    assert parse_time_range("12:00–24:00") == ("12:00", "24:00")
    assert parse_time_range("21-11") is None
    assert parse_time_range("25-26") is None


def test_formatting():
    assert fmt_money(6_000_000) == "60 000 ₽"
    assert fmt_money(350_050) == "3 500,50 ₽"
    assert plural(1, ("смена", "смены", "смен")) == "1 смена"
    assert plural(3, ("смена", "смены", "смен")) == "3 смены"
    assert plural(11, ("смена", "смены", "смен")) == "11 смен"
    assert plural(22, ("смена", "смены", "смен")) == "22 смены"


# --- planner --------------------------------------------------------------------------------


def month_days(year, month):
    d = date(year, month, 1)
    days = []
    while d.month == month:
        days.append(d)
        d += timedelta(days=1)
    return days


def max_streak_of(assignments, master):
    """Longest run of consecutive calendar days worked (closed days break a run)."""
    best = current = 0
    day, last = min(assignments), max(assignments)
    while day <= last:
        current = current + 1 if master in assignments.get(day, []) else 0
        best = max(best, current)
        day += timedelta(days=1)
    return best


def test_planner_is_fair_and_full():
    days = month_days(2026, 11)
    result = plan_shifts(days, [1, 2, 3, 4], set(range(7)), per_day=2, max_streak=5)
    assert not result.shortages
    assert all(len(v) == 2 for v in result.assignments.values())
    assert max(result.counts.values()) - min(result.counts.values()) <= 1
    assert sum(result.counts.values()) == 2 * len(days)


def test_planner_respects_days_off_closed_days_and_streak():
    days = month_days(2026, 11)
    off = {1: {date(2026, 11, d) for d in range(10, 15)}}
    open_days = {1, 2, 3, 4, 5, 6}  # closed on Mondays
    result = plan_shifts(days, [1, 2, 3], open_days, per_day=2, max_streak=3, days_off=off)
    assert all(d.weekday() != 0 for d in result.assignments)
    for d in off[1]:
        assert 1 not in result.assignments.get(d, [])
    for m in (1, 2, 3):
        assert max_streak_of(result.assignments, m) <= 3


def test_planner_reports_shortage():
    days = [date(2026, 11, 2)]
    result = plan_shifts(days, [1, 2], {0}, per_day=3, max_streak=5)
    assert result.shortages == {date(2026, 11, 2): 1}


def test_planner_weekends_are_shared():
    days = month_days(2026, 11)
    result = plan_shifts(days, [1, 2, 3, 4], set(range(7)), per_day=1, max_streak=7)
    weekend = {m: sum(m in v for d, v in result.assignments.items() if d.weekday() >= 5) for m in (1, 2, 3, 4)}
    assert max(weekend.values()) - min(weekend.values()) <= 1


def test_planner_carries_streak_from_previous_days():
    days = [date(2026, 11, 1), date(2026, 11, 2)]
    result = plan_shifts(days, [1, 2], set(range(7)), per_day=1, max_streak=3, initial_streak={1: 3})
    assert result.assignments[date(2026, 11, 1)] == [2]


# --- payments -------------------------------------------------------------------------------


def planned(period, day=None, once_day=None, start=date(2026, 1, 1), pid=1):
    return Planned(pid, "Аренда", "rent", 6_000_000, period, day, once_day, start)


def test_monthly_payment_on_31st_uses_last_day():
    p = planned("monthly", day=31)
    assert occurrences(p, date(2026, 2, 1), date(2026, 4, 30)) == [
        date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)
    ]


def test_payment_does_not_start_before_creation():
    p = planned("monthly", day=5, start=date(2026, 10, 21))
    assert occurrences(p, date(2026, 10, 1), date(2026, 11, 30)) == [date(2026, 11, 5)]


def test_weekly_and_once_payments():
    weekly = planned("weekly", day=4)  # Fridays
    assert occurrences(weekly, date(2026, 10, 1), date(2026, 10, 31)) == [
        date(2026, 10, 2), date(2026, 10, 9), date(2026, 10, 16), date(2026, 10, 23), date(2026, 10, 30)
    ]
    once = planned("once", once_day=date(2026, 11, 15))
    assert occurrences(once, date(2026, 11, 1), date(2026, 11, 30)) == [date(2026, 11, 15)]
    assert occurrences(once, date(2026, 12, 1), date(2026, 12, 31)) == []


def test_schedule_marks_paid():
    p = planned("monthly", day=1)
    plan = schedule([p], date(2026, 10, 1), date(2026, 11, 30), paid={(1, date(2026, 10, 1))})
    assert [(o.due, o.paid) for o in plan] == [(date(2026, 10, 1), True), (date(2026, 11, 1), False)]
