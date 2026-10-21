"""Telegram message texts (HTML parse mode)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from html import escape

from .db import DayOff, Expense, Master, Settings, Shift
from .fmt import (
    CATEGORIES,
    MONTHS,
    WEEKDAYS_SHORT,
    category_label,
    days_between,
    fmt_date,
    fmt_day,
    fmt_money,
    plural,
)
from .payments import Occurrence, Planned
from .planner import PlanResult

SHIFTS = ("смена", "смены", "смен")


def _by_day(items: list[Shift] | list[DayOff]) -> dict[date, list]:
    grouped: dict[date, list] = defaultdict(list)
    for item in items:
        grouped[item.day].append(item)
    return grouped


def render_week(
    start: date, shifts: list[Shift], days_off: list[DayOff], settings: Settings, today: date
) -> str:
    end = start + timedelta(days=6)
    shifts_by_day, off_by_day = _by_day(shifts), _by_day(days_off)
    empty_mark = "нет смен" if not shifts else "⚠️ никого нет"
    lines = [f"📅 <b>График {fmt_date(start)} – {fmt_date(end)}</b>", ""]
    for day in days_between(start, end):
        head = f"{'👉 ' if day == today else ''}<b>{fmt_day(day)}</b>"
        day_shifts = shifts_by_day.get(day, [])
        if not day_shifts:
            closed = day.weekday() not in settings.open_weekdays
            lines.append(f"{head} — {'выходной салона' if closed else empty_mark}")
        else:
            lines.append(head)
            lines += [f"    • {escape(s.master_name)} {s.start}–{s.end}" for s in day_shifts]
        if off := off_by_day.get(day):
            lines.append(f"    🌴 выходной: {', '.join(escape(o.master_name) for o in off)}")
    counts = Counter(s.master_name for s in shifts)
    if counts:
        summary = ", ".join(f"{escape(name)} — {n}" for name, n in counts.most_common())
        lines += ["", f"Смен за неделю: {summary}"]
    else:
        lines += ["", "На этой неделе график ещё не составлен."]
    return "\n".join(lines)


def render_day_editor(
    day: date, masters: list[Master], shifts: list[Shift], days_off: list[DayOff], settings: Settings
) -> str:
    working = {s.master_id: s for s in shifts}
    off = {o.master_id for o in days_off}
    closed = day.weekday() not in settings.open_weekdays
    lines = [f"✏️ <b>{fmt_day(day)}.{day.year}</b>" + (" — выходной салона" if closed else "")]
    lines.append("Нажмите на мастера, чтобы поставить или снять смену.\n")
    if not masters:
        lines.append("Мастеров пока нет — добавьте их в разделе «👥 Мастера».")
    for m in masters:
        if m.id in working:
            s = working[m.id]
            lines.append(f"✅ {escape(m.name)} {s.start}–{s.end}")
        else:
            lines.append(f"▫️ {escape(m.name)}" + (" — 🌴 просил(а) выходной" if m.id in off else ""))
    return "\n".join(lines)


def render_master_shifts(master: Master, shifts: list[Shift], days: int) -> str:
    if not shifts:
        return f"🗓 <b>{escape(master.name)}</b>, в ближайшие {days} дней смен нет."
    lines = [f"🗓 <b>Ваши смены, {escape(master.name)}</b>", ""]
    lines += [f"{fmt_day(s.day)} · {s.start}–{s.end}" for s in shifts]
    lines += ["", f"Всего: {plural(len(shifts), SHIFTS)} за {days} дней"]
    return "\n".join(lines)


def render_generation(
    year: int, month: int, start: date, end: date, result: PlanResult, masters: list[Master], settings: Settings
) -> str:
    lines = [
        f"⚡ <b>График на {MONTHS[month - 1]} {year} составлен</b>",
        f"Период {fmt_date(start)} – {fmt_date(end)}: по {settings.per_day} в смену, "
        f"не больше {settings.max_streak} дней подряд, часы {settings.day_start}–{settings.day_end}.",
        "",
        "Смен у мастеров:",
    ]
    lines += [f"    • {escape(m.name)} — {result.counts.get(m.id, 0)}" for m in masters]
    if result.shortages:
        missing = ", ".join(f"{fmt_date(d)} (−{n})" for d, n in sorted(result.shortages.items()))
        lines += ["", f"⚠️ Не хватило мастеров: {missing}"]
    lines += ["", "Поправить отдельный день — кнопки «✏️» под графиком недели (📅 График работы)."]
    return "\n".join(lines)


def render_masters(masters: list[Master], counts: Counter[int], year: int, month: int) -> str:
    if not masters:
        return "👥 <b>Мастера</b>\n\nПока никого нет. Нажмите «➕ Добавить мастеров»."
    lines = [f"👥 <b>Мастера</b> · смены за {MONTHS[month - 1]} {year}", ""]
    for m in masters:
        linked = " · 📱 в боте" if m.telegram_id else ""
        lines.append(f"• {escape(m.name)} — {plural(counts.get(m.id, 0), SHIFTS)}{linked}")
    lines += ["", "Нажмите на мастера, чтобы переименовать, удалить или пригласить в бота."]
    return "\n".join(lines)


def render_master_card(master: Master, upcoming_off: list[DayOff]) -> str:
    lines = [f"👤 <b>{escape(master.name)}</b>"]
    lines.append("📱 Подключён к боту" if master.telegram_id else "📱 Не подключён к боту")
    if upcoming_off:
        lines.append("🌴 Выходные: " + ", ".join(fmt_date(o.day) for o in upcoming_off))
    return "\n".join(lines)


def render_days_off(days_off: list[DayOff]) -> str:
    if not days_off:
        return "🌴 <b>Выходные мастеров</b>\n\nВ ближайшие 60 дней никто не просил выходных."
    lines = ["🌴 <b>Выходные мастеров</b> (учитываются при составлении графика)", ""]
    lines += [f"{fmt_day(o.day)} — {escape(o.master_name)}" for o in days_off]
    lines += ["", "Нажмите на запись ниже, чтобы удалить её."]
    return "\n".join(lines)


def render_expense_saved(expense: Expense, currency: str) -> str:
    comment = f" · {escape(expense.comment)}" if expense.comment else ""
    return (
        f"✅ Записал: {category_label(expense.category)} — <b>{fmt_money(expense.amount, currency)}</b>"
        f" ({fmt_day(expense.day)}){comment}"
    )


def render_recent(expenses: list[Expense], currency: str) -> str:
    if not expenses:
        return "🧾 Расходов пока нет."
    lines = ["🧾 <b>Последние расходы</b>", ""]
    for e in expenses:
        comment = f" · {escape(e.comment)}" if e.comment else ""
        lines.append(f"{fmt_date(e.day)} {category_label(e.category)} — {fmt_money(e.amount, currency)}{comment}")
    lines += ["", "Чтобы удалить ошибочную запись, нажмите 🗑 под ней."]
    return "\n".join(lines)


def category_totals(expenses: list[Expense]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for e in expenses:
        totals[e.category] += e.amount
    return dict(totals)


def render_report(
    year: int,
    month: int,
    expenses: list[Expense],
    prev_total: int,
    prev_month: int,
    plan: list[Occurrence],
    currency: str,
) -> str:
    totals = category_totals(expenses)
    total = sum(totals.values())
    lines = [f"📊 <b>Расходы за {MONTHS[month - 1]} {year}</b>", ""]
    if not total:
        lines.append("Расходов за этот месяц нет.")
    else:
        order = {c.code: i for i, c in enumerate(CATEGORIES)}
        for code, amount in sorted(totals.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99))):
            share = round(amount * 100 / total)
            lines.append(f"{category_label(code)} — {fmt_money(amount, currency)} ({share}%)")
        lines += ["", f"<b>Итого: {fmt_money(total, currency)}</b> · {plural(len(expenses), ('запись', 'записи', 'записей'))}"]
        if prev_total:
            change = round((total - prev_total) * 100 / prev_total)
            sign = "+" if change > 0 else ""
            lines.append(
                f"К прошлому месяцу ({MONTHS[prev_month - 1]}): {sign}{change}%, было {fmt_money(prev_total, currency)}"
            )
    if plan:
        planned = sum(o.planned.amount for o in plan)
        paid = sum(o.planned.amount for o in plan if o.paid)
        lines += [
            "",
            f"🗓 По графику платежей: оплачено {fmt_money(paid, currency)} из {fmt_money(planned, currency)}, "
            f"осталось {fmt_money(planned - paid, currency)}.",
        ]
    return "\n".join(lines)


def payment_status(o: Occurrence, today: date) -> str:
    if o.paid:
        return "✅"
    if o.due < today:
        return "❗"
    return "⏳"


def render_payments(year: int, month: int, plan: list[Occurrence], today: date, currency: str) -> str:
    lines = [f"🗓 <b>График платежей — {MONTHS[month - 1]} {year}</b>", ""]
    if not plan:
        lines.append("На этот месяц платежей нет. Добавьте аренду, коммуналку, закупки — «➕ Новый платёж».")
        return "\n".join(lines)
    for o in plan:
        overdue = " — просрочен" if not o.paid and o.due < today else ""
        lines.append(
            f"{payment_status(o, today)} {fmt_day(o.due)} {escape(o.planned.title)} — "
            f"{fmt_money(o.planned.amount, currency)}{overdue}"
        )
    planned = sum(o.planned.amount for o in plan)
    paid = sum(o.planned.amount for o in plan if o.paid)
    lines += [
        "",
        f"Всего: {fmt_money(planned, currency)} · оплачено: {fmt_money(paid, currency)} · "
        f"осталось: <b>{fmt_money(planned - paid, currency)}</b>",
        "",
        "✅ оплачено · ⏳ предстоит · ❗ просрочено",
    ]
    return "\n".join(lines)


def render_planned_list(plans: list[Planned], currency: str) -> str:
    if not plans:
        return "📋 Регулярных платежей пока нет."
    lines = ["📋 <b>Все платежи</b>", ""]
    for p in plans:
        lines.append(
            f"• {escape(p.title)} — {fmt_money(p.amount, currency)}, {p.describe()} ({category_label(p.category)})"
        )
    lines += ["", "Нажмите 🗑, чтобы убрать платёж из графика (уже оплаченные останутся в расходах)."]
    return "\n".join(lines)


def render_settings(settings: Settings) -> str:
    days = " ".join(WEEKDAYS_SHORT[d] for d in sorted(settings.open_weekdays)) or "—"
    reminders = f"в {settings.reminder_time}" if settings.reminders_on else "выключены"
    return "\n".join(
        [
            "⚙️ <b>Настройки</b>",
            "",
            f"Рабочие дни салона: {days}",
            f"Часы смены по умолчанию: {settings.day_start}–{settings.day_end}",
            f"Мастеров в смену: {settings.per_day}",
            f"Максимум дней подряд: {settings.max_streak}",
            f"Напоминания: {reminders}",
        ]
    )


def render_tomorrow_digest(
    tomorrow: date, shifts: list[Shift], due: list[Occurrence], today: date, currency: str
) -> str | None:
    lines = []
    if shifts:
        lines.append(f"📅 <b>Завтра, {fmt_day(tomorrow)}</b>, работают:")
        lines += [f"    • {escape(s.master_name)} {s.start}–{s.end}" for s in shifts]
    if due:
        if lines:
            lines.append("")
        lines.append("💸 <b>Платежи</b>:")
        for o in due:
            when = "просрочен" if o.due < today else ("сегодня" if o.due == today else fmt_day(o.due))
            lines.append(
                f"    {payment_status(o, today)} {escape(o.planned.title)} — "
                f"{fmt_money(o.planned.amount, currency)} ({when})"
            )
    return "\n".join(lines) if lines else None
