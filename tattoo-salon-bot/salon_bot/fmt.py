"""Russian date, money and category formatting shared by views, charts and exports."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_EVERY = [
    "каждый понедельник",
    "каждый вторник",
    "каждую среду",
    "каждый четверг",
    "каждую пятницу",
    "каждую субботу",
    "каждое воскресенье",
]
MONTHS = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


@dataclass(frozen=True)
class Category:
    code: str
    emoji: str
    title: str

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.title}"


CATEGORIES = [
    Category("rent", "🏠", "Аренда"),
    Category("supplies", "🧴", "Расходники"),
    Category("equipment", "🛠", "Оборудование"),
    Category("utilities", "💡", "Коммуналка и связь"),
    Category("salary", "👥", "Зарплата"),
    Category("marketing", "📣", "Реклама"),
    Category("taxes", "🧾", "Налоги"),
    Category("other", "📦", "Прочее"),
]
CATEGORY_BY_CODE = {c.code: c for c in CATEGORIES}


def category_label(code: str) -> str:
    cat = CATEGORY_BY_CODE.get(code)
    return cat.label if cat else code


def category_title(code: str) -> str:
    cat = CATEGORY_BY_CODE.get(code)
    return cat.title if cat else code


def fmt_money(kopecks: int, currency: str = "₽") -> str:
    sign = "−" if kopecks < 0 else ""
    rub, kop = divmod(abs(kopecks), 100)
    whole = f"{rub:,}".replace(",", " ")
    if kop:
        return f"{sign}{whole},{kop:02d} {currency}"
    return f"{sign}{whole} {currency}"


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m")


def fmt_day(d: date) -> str:
    return f"{WEEKDAYS_SHORT[d.weekday()]} {fmt_date(d)}"


def month_title(year: int, month: int) -> str:
    return f"{MONTHS[month - 1].capitalize()} {year}"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n_abs = abs(n) % 100
    if 11 <= n_abs <= 14:
        form = forms[2]
    elif n_abs % 10 == 1:
        form = forms[0]
    elif 2 <= n_abs % 10 <= 4:
        form = forms[1]
    else:
        form = forms[2]
    return f"{n} {form}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def ym(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_ym(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
