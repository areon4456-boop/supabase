from __future__ import annotations

from datetime import date, timedelta

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from .callbacks import (
    CatCb,
    DayCb,
    ExpCb,
    MasterCb,
    MonthCb,
    OffCb,
    PayCb,
    PeriodCb,
    ReportCb,
    SetCb,
    WeekCb,
    WeekdayCb,
)
from .db import DayOff, Master, Settings, Shift
from .fmt import (
    CATEGORIES,
    MONTHS,
    MONTHS_SHORT,
    WEEKDAYS_SHORT,
    days_between,
    fmt_date,
    fmt_day,
    shift_month,
    week_start,
    ym,
)
from .payments import Occurrence, Planned

# Reply keyboard labels double as message filters in handlers.
BTN_SCHEDULE = "📅 График работы"
BTN_EXPENSES = "💸 Расходы"
BTN_PAYMENTS = "🗓 Платежи"
BTN_MASTERS = "👥 Мастера"
BTN_SETTINGS = "⚙️ Настройки"
BTN_MY_SHIFTS = "📅 Мои смены"
BTN_SALON_WEEK = "📆 График салона"
BTN_DAY_OFF = "🌴 Хочу выходной"
BTN_CANCEL = "❌ Отмена"

ADMIN_BUTTONS = {BTN_SCHEDULE, BTN_EXPENSES, BTN_PAYMENTS, BTN_MASTERS, BTN_SETTINGS}
STAFF_BUTTONS = {BTN_MY_SHIFTS, BTN_SALON_WEEK, BTN_DAY_OFF}


def admin_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    for text in (BTN_SCHEDULE, BTN_EXPENSES, BTN_PAYMENTS, BTN_MASTERS, BTN_SETTINGS):
        kb.button(text=text)
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="Например: 3500 краска")


def staff_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    for text in (BTN_MY_SHIFTS, BTN_SALON_WEEK, BTN_DAY_OFF):
        kb.button(text=text)
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)


def cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BTN_CANCEL, callback_data="cancel")
    return kb.as_markup()


def week_kb(start: date, today: date, is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️", callback_data=WeekCb(start=(start - timedelta(days=7)).isoformat()))
    kb.button(text="Эта неделя", callback_data=WeekCb(start=week_start(today).isoformat()))
    kb.button(text="▶️", callback_data=WeekCb(start=(start + timedelta(days=7)).isoformat()))
    sizes = [3]
    if is_admin:
        for day in days_between(start, start + timedelta(days=6)):
            kb.button(text=f"✏️ {fmt_day(day)}", callback_data=DayCb(action="open", day=day.isoformat()))
        sizes += [4, 3]
        this_y, this_m = start.year, start.month
        next_y, next_m = shift_month(this_y, this_m, 1)
        kb.button(text=f"⚡ Составить: {MONTHS[this_m - 1]}", callback_data=MonthCb(action="gen", ym=ym(this_y, this_m)))
        kb.button(text=f"⚡ {MONTHS[next_m - 1]}", callback_data=MonthCb(action="gen", ym=ym(next_y, next_m)))
        kb.button(text="🖼 Месяц картинкой", callback_data=MonthCb(action="img", ym=ym(this_y, this_m)))
        kb.button(text="📤 Excel", callback_data=MonthCb(action="xlsx", ym=ym(this_y, this_m)))
        kb.button(text="🌴 Выходные мастеров", callback_data=OffCb(action="list"))
        sizes += [2, 2, 1]
    else:
        kb.button(text="🖼 Месяц картинкой", callback_data=MonthCb(action="img", ym=ym(start.year, start.month)))
        sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()


def month_image_kb(year: int, month: int, is_admin: bool) -> InlineKeyboardMarkup:
    prev_y, prev_m = shift_month(year, month, -1)
    next_y, next_m = shift_month(year, month, 1)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"◀️ {MONTHS_SHORT[prev_m - 1]}", callback_data=MonthCb(action="img", ym=ym(prev_y, prev_m)))
    kb.button(text=f"{MONTHS_SHORT[next_m - 1]} ▶️", callback_data=MonthCb(action="img", ym=ym(next_y, next_m)))
    if is_admin:
        kb.button(text="📤 Excel", callback_data=MonthCb(action="xlsx", ym=ym(year, month)))
    kb.adjust(2, 1)
    return kb.as_markup()


def generate_confirm_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, составить заново", callback_data=MonthCb(action="genok", ym=ym(year, month)))
    kb.button(text=BTN_CANCEL, callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def day_editor_kb(day: date, masters: list[Master], shifts: list[Shift]) -> InlineKeyboardMarkup:
    working = {s.master_id for s in shifts}
    kb = InlineKeyboardBuilder()
    sizes = []
    for m in masters:
        iso = day.isoformat()
        if m.id in working:
            kb.button(text=f"✅ {m.name}", callback_data=DayCb(action="toggle", day=iso, master_id=m.id))
            kb.button(text="🕐 часы", callback_data=DayCb(action="hours", day=iso, master_id=m.id))
            sizes.append(2)
        else:
            kb.button(text=f"▫️ {m.name}", callback_data=DayCb(action="toggle", day=iso, master_id=m.id))
            sizes.append(1)
    kb.button(text=f"◀️ {fmt_date(day - timedelta(days=1))}",
              callback_data=DayCb(action="open", day=(day - timedelta(days=1)).isoformat()))
    kb.button(text=f"{fmt_date(day + timedelta(days=1))} ▶️",
              callback_data=DayCb(action="open", day=(day + timedelta(days=1)).isoformat()))
    kb.button(text="⬅️ К неделе", callback_data=WeekCb(start=week_start(day).isoformat()))
    kb.adjust(*sizes, 2, 1)
    return kb.as_markup()


def days_off_kb(days_off: list[DayOff]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in days_off[:30]:
        kb.button(text=f"🗑 {fmt_date(o.day)} {o.master_name}",
                  callback_data=OffCb(action="del", master_id=o.master_id, day=o.day.isoformat()))
    kb.button(text="➕ Добавить выходной", callback_data=OffCb(action="add"))
    kb.adjust(2)
    return kb.as_markup()


def choose_master_kb(masters: list[Master], action: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in masters:
        kb.button(text=m.name, callback_data=MasterCb(action=action, id=m.id))
    kb.button(text=BTN_CANCEL, callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def masters_kb(masters: list[Master]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in masters:
        kb.button(text=f"👤 {m.name}", callback_data=MasterCb(action="open", id=m.id))
    kb.button(text="➕ Добавить мастеров", callback_data=MasterCb(action="add"))
    kb.adjust(2)
    return kb.as_markup()


def master_card_kb(master: Master) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Переименовать", callback_data=MasterCb(action="rename", id=master.id))
    kb.button(text="🌴 Выходной", callback_data=MasterCb(action="off", id=master.id))
    if master.telegram_id:
        kb.button(text="📵 Отключить от бота", callback_data=MasterCb(action="unlink", id=master.id))
    else:
        kb.button(text="🔗 Пригласить в бота", callback_data=MasterCb(action="invite", id=master.id))
    kb.button(text="🗑 Удалить", callback_data=MasterCb(action="delete", id=master.id))
    kb.button(text="⬅️ Все мастера", callback_data=MasterCb(action="list"))
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def confirm_delete_master_kb(master: Master) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=MasterCb(action="delok", id=master.id))
    kb.button(text="⬅️ Нет", callback_data=MasterCb(action="open", id=master.id))
    kb.adjust(2)
    return kb.as_markup()


def expenses_menu_kb(today: date) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить расход", callback_data=ExpCb(action="add"))
    kb.button(text="📊 Отчёт за месяц", callback_data=ReportCb(action="show", ym=ym(today.year, today.month)))
    kb.button(text="🧾 Последние записи", callback_data=ExpCb(action="recent"))
    kb.button(text="🗓 График платежей", callback_data=PayCb(action="month", ym=ym(today.year, today.month)))
    kb.adjust(1, 1, 2)
    return kb.as_markup()


def categories_kb(flow: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in CATEGORIES:
        kb.button(text=c.label, callback_data=CatCb(flow=flow, code=c.code))
    kb.button(text=BTN_CANCEL, callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def expense_saved_kb(expense_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Отменить", callback_data=ExpCb(action="del", id=expense_id))
    kb.button(text="➕ Ещё расход", callback_data=ExpCb(action="add"))
    kb.adjust(2)
    return kb.as_markup()


def recent_kb(expense_ids: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for expense_id, label in expense_ids:
        kb.button(text=f"🗑 {label}", callback_data=ExpCb(action="delr", id=expense_id))
    kb.adjust(1)
    return kb.as_markup()


def report_kb(year: int, month: int) -> InlineKeyboardMarkup:
    prev_y, prev_m = shift_month(year, month, -1)
    next_y, next_m = shift_month(year, month, 1)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"◀️ {MONTHS_SHORT[prev_m - 1]}", callback_data=ReportCb(action="show", ym=ym(prev_y, prev_m)))
    kb.button(text=f"{MONTHS_SHORT[next_m - 1]} ▶️", callback_data=ReportCb(action="show", ym=ym(next_y, next_m)))
    kb.button(text="📈 Диаграмма", callback_data=ReportCb(action="chart", ym=ym(year, month)))
    kb.button(text="📤 Excel", callback_data=ReportCb(action="xlsx", ym=ym(year, month)))
    kb.adjust(2, 2)
    return kb.as_markup()


def payments_kb(year: int, month: int, plan: list[Occurrence]) -> InlineKeyboardMarkup:
    prev_y, prev_m = shift_month(year, month, -1)
    next_y, next_m = shift_month(year, month, 1)
    kb = InlineKeyboardBuilder()
    unpaid = [o for o in plan if not o.paid][:10]
    for o in unpaid:
        kb.button(
            text=f"💳 Отметить оплату · {fmt_date(o.due)} {o.planned.title}",
            callback_data=PayCb(action="pay", ym=ym(year, month), id=o.planned.id, due=o.due.isoformat()),
        )
    kb.button(text=f"◀️ {MONTHS_SHORT[prev_m - 1]}", callback_data=PayCb(action="month", ym=ym(prev_y, prev_m)))
    kb.button(text=f"{MONTHS_SHORT[next_m - 1]} ▶️", callback_data=PayCb(action="month", ym=ym(next_y, next_m)))
    kb.button(text="➕ Новый платёж", callback_data=PayCb(action="new"))
    kb.button(text="📋 Все платежи", callback_data=PayCb(action="list"))
    kb.adjust(*([1] * len(unpaid)), 2, 2)
    return kb.as_markup()


def planned_list_kb(plans: list[Planned]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in plans:
        kb.button(text=f"🗑 {p.title}", callback_data=PayCb(action="del", id=p.id))
    kb.button(text="➕ Новый платёж", callback_data=PayCb(action="new"))
    kb.adjust(2)
    return kb.as_markup()


def period_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Каждый месяц", callback_data=PeriodCb(period="monthly"))
    kb.button(text="Каждую неделю", callback_data=PeriodCb(period="weekly"))
    kb.button(text="Один раз", callback_data=PeriodCb(period="once"))
    kb.button(text=BTN_CANCEL, callback_data="cancel")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def weekday_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, name in enumerate(WEEKDAYS_SHORT):
        kb.button(text=name, callback_data=WeekdayCb(day=i))
    kb.adjust(7)
    return kb.as_markup()


def settings_kb(settings: Settings) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📆 Рабочие дни", callback_data=SetCb(action="days"))
    kb.button(text="🕐 Часы смены", callback_data=SetCb(action="hours"))
    kb.button(text="👥 Мастеров в смену", callback_data=SetCb(action="perday"))
    kb.button(text="🔁 Дней подряд", callback_data=SetCb(action="streak"))
    kb.button(text="⏰ Время напоминаний", callback_data=SetCb(action="remtime"))
    kb.button(
        text="🔕 Выключить напоминания" if settings.reminders_on else "🔔 Включить напоминания",
        callback_data=SetCb(action="remtoggle"),
    )
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def weekdays_toggle_kb(open_weekdays: set[int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, name in enumerate(WEEKDAYS_SHORT):
        kb.button(text=f"{'✅' if i in open_weekdays else '▫️'} {name}", callback_data=SetCb(action="day", value=i))
    kb.button(text="Готово", callback_data=SetCb(action="show"))
    kb.adjust(4, 3, 1)
    return kb.as_markup()


def numbers_kb(action: str, values: list[tuple[int, str]], current: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in values:
        kb.button(text=f"• {label} •" if value == current else label, callback_data=SetCb(action=action, value=value))
    kb.button(text="⬅️ Назад", callback_data=SetCb(action="show"))
    kb.adjust(len(values), 1)
    return kb.as_markup()


def day_buttons_kb(days: list[date]) -> InlineKeyboardMarkup:
    """Buttons that open the day editor (used in admin notifications)."""
    kb = InlineKeyboardBuilder()
    for day in days[:8]:
        kb.button(text=f"✏️ {fmt_day(day)}", callback_data=DayCb(action="open", day=day.isoformat()))
    kb.adjust(2)
    return kb.as_markup()
