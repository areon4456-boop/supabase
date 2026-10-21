from __future__ import annotations

import asyncio
from datetime import date, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message

from ..access import ADMIN, MASTER, RoleFilter
from ..callbacks import DayCb, MonthCb, OffCb, WeekCb
from ..charts import schedule_png
from ..config import Config
from ..db import Database, Master
from ..excel import schedule_xlsx
from ..fmt import MONTHS, fmt_date, fmt_day, month_bounds, month_title, parse_ym, plural, week_start
from ..keyboards import (
    BTN_SALON_WEEK,
    BTN_SCHEDULE,
    cancel_kb,
    choose_master_kb,
    day_buttons_kb,
    day_editor_kb,
    days_off_kb,
    generate_confirm_kb,
    month_image_kb,
    week_kb,
)
from ..parsing import parse_dates, parse_time_range
from ..services import generate_month, generation_period, local_today
from ..states import DaysOffInput, ShiftHours
from ..views import SHIFTS, render_day_editor, render_days_off, render_generation, render_week
from .utils import TEXT_INPUT, chat_id, edit_or_send, notify_admins

router = Router(name="schedule")


async def week_view(db: Database, start: date, today: date, role: str):
    settings = await db.get_settings()
    end = start + timedelta(days=6)
    shifts = await db.shifts_between(start, end)
    days_off = await db.days_off_between(start, end)
    return render_week(start, shifts, days_off, settings, today), week_kb(start, today, role == ADMIN)


@router.message(F.text == BTN_SCHEDULE, RoleFilter(ADMIN))
@router.message(F.text == BTN_SALON_WEEK, RoleFilter(ADMIN, MASTER))
async def show_week(message: Message, state: FSMContext, db: Database, config: Config, role: str) -> None:
    await state.clear()
    today = local_today(config.tz)
    text, markup = await week_view(db, week_start(today), today, role)
    await message.answer(text, reply_markup=markup)


@router.callback_query(WeekCb.filter(), RoleFilter(ADMIN, MASTER))
async def navigate_week(
    callback: CallbackQuery, callback_data: WeekCb, db: Database, config: Config, role: str, bot: Bot
) -> None:
    today = local_today(config.tz)
    text, markup = await week_view(db, date.fromisoformat(callback_data.start), today, role)
    await edit_or_send(callback, bot, text, markup)
    await callback.answer()


# --- month picture, Excel, automatic planning ------------------------------------------------


async def month_png(db: Database, year: int, month: int, today: date) -> bytes:
    first, last = month_bounds(year, month)
    settings = await db.get_settings()
    masters = await db.list_masters()
    shifts = await db.shifts_between(first, last)
    days_off = await db.days_off_between(first, last)
    return await asyncio.to_thread(
        schedule_png, year, month, masters, shifts, days_off, settings.open_weekdays, today
    )


@router.callback_query(MonthCb.filter(F.action == "img"), RoleFilter(ADMIN, MASTER))
async def month_image(
    callback: CallbackQuery, callback_data: MonthCb, db: Database, config: Config, role: str, bot: Bot
) -> None:
    year, month = parse_ym(callback_data.ym)
    png = await month_png(db, year, month, local_today(config.tz))
    photo = BufferedInputFile(png, filename=f"grafik-{callback_data.ym}.png")
    caption = f"📅 График работы · {month_title(year, month)}"
    markup = month_image_kb(year, month, role == ADMIN)
    if isinstance(callback.message, Message) and callback.message.photo:
        await callback.message.edit_media(InputMediaPhoto(media=photo, caption=caption), reply_markup=markup)
    else:
        await bot.send_photo(chat_id(callback), photo, caption=caption, reply_markup=markup)
    await callback.answer()


@router.callback_query(MonthCb.filter(F.action == "xlsx"), RoleFilter(ADMIN))
async def month_excel(callback: CallbackQuery, callback_data: MonthCb, db: Database, bot: Bot) -> None:
    year, month = parse_ym(callback_data.ym)
    first, last = month_bounds(year, month)
    settings = await db.get_settings()
    data = await asyncio.to_thread(
        schedule_xlsx,
        year,
        month,
        await db.list_masters(),
        await db.shifts_between(first, last),
        await db.days_off_between(first, last),
        settings.open_weekdays,
    )
    await bot.send_document(
        chat_id(callback),
        BufferedInputFile(data, filename=f"grafik-{callback_data.ym}.xlsx"),
        caption=f"📤 График работы · {month_title(year, month)}",
    )
    await callback.answer()


@router.callback_query(MonthCb.filter(F.action == "gen"), RoleFilter(ADMIN))
async def generate_ask(
    callback: CallbackQuery, callback_data: MonthCb, db: Database, config: Config, bot: Bot
) -> None:
    year, month = parse_ym(callback_data.ym)
    today = local_today(config.tz)
    period = generation_period(year, month, today)
    if period is None:
        await callback.answer("Этот месяц уже прошёл.", show_alert=True)
        return
    if not await db.list_masters():
        await callback.answer("Сначала добавьте мастеров в разделе «👥 Мастера».", show_alert=True)
        return
    existing = await db.shifts_between(*period)
    if existing:
        start, end = period
        await bot.send_message(
            chat_id(callback),
            f"На период {fmt_date(start)} – {fmt_date(end)} уже стоит {plural(len(existing), SHIFTS)}.\n"
            "Составить график заново? Ручные правки за этот период пропадут.",
            reply_markup=generate_confirm_kb(year, month),
        )
        await callback.answer()
        return
    await callback.answer("Составляю график…")
    await _generate(callback, db, year, month, today, bot)


@router.callback_query(MonthCb.filter(F.action == "genok"), RoleFilter(ADMIN))
async def generate_confirmed(
    callback: CallbackQuery, callback_data: MonthCb, db: Database, config: Config, bot: Bot
) -> None:
    year, month = parse_ym(callback_data.ym)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"⚡ Составляю график на {MONTHS[month - 1]}…")
    await callback.answer()
    await _generate(callback, db, year, month, local_today(config.tz), bot)


async def _generate(callback: CallbackQuery, db: Database, year: int, month: int, today: date, bot: Bot) -> None:
    generation = await generate_month(db, year, month, today)
    if generation is None:
        await bot.send_message(chat_id(callback), "Этот месяц уже прошёл.")
        return
    text = render_generation(
        year, month, generation.start, generation.end, generation.result, generation.masters, generation.settings
    )
    await bot.send_message(chat_id(callback), text)
    png = await month_png(db, year, month, today)
    await bot.send_photo(
        chat_id(callback),
        BufferedInputFile(png, filename=f"grafik-{year}-{month:02d}.png"),
        caption=f"📅 График работы · {month_title(year, month)}",
        reply_markup=month_image_kb(year, month, True),
    )


# --- single day editor -----------------------------------------------------------------------


async def day_editor(db: Database, day: date):
    settings = await db.get_settings()
    masters = await db.list_masters()
    shifts = await db.shifts_between(day, day)
    days_off = await db.days_off_between(day, day)
    return (
        render_day_editor(day, masters, shifts, days_off, settings),
        day_editor_kb(day, masters, shifts),
    )


@router.callback_query(DayCb.filter(F.action == "open"), RoleFilter(ADMIN))
async def open_day(callback: CallbackQuery, callback_data: DayCb, db: Database, bot: Bot) -> None:
    text, markup = await day_editor(db, date.fromisoformat(callback_data.day))
    await edit_or_send(callback, bot, text, markup)
    await callback.answer()


async def _active_master(db: Database, master_id: int) -> Master | None:
    master = await db.get_master(master_id)
    return master if master and master.active else None


@router.callback_query(DayCb.filter(F.action == "toggle"), RoleFilter(ADMIN))
async def toggle_shift(callback: CallbackQuery, callback_data: DayCb, db: Database, bot: Bot) -> None:
    day = date.fromisoformat(callback_data.day)
    if not await _active_master(db, callback_data.master_id):
        await callback.answer("Мастер удалён.", show_alert=True)
        return
    if await db.shifts_between(day, day, master_id=callback_data.master_id):
        await db.delete_shift(callback_data.master_id, day)
    else:
        settings = await db.get_settings()
        await db.set_shift(callback_data.master_id, day, settings.day_start, settings.day_end)
    text, markup = await day_editor(db, day)
    await edit_or_send(callback, bot, text, markup)
    await callback.answer()


@router.callback_query(DayCb.filter(F.action == "hours"), RoleFilter(ADMIN))
async def ask_hours(
    callback: CallbackQuery, callback_data: DayCb, state: FSMContext, db: Database, bot: Bot
) -> None:
    master = await _active_master(db, callback_data.master_id)
    if not master:
        await callback.answer("Мастер удалён.", show_alert=True)
        return
    day = date.fromisoformat(callback_data.day)
    await state.set_state(ShiftHours.hours)
    await state.update_data(day=callback_data.day, master_id=master.id)
    await bot.send_message(
        chat_id(callback),
        f"🕐 {escape(master.name)}, {fmt_day(day)}: напишите часы смены, например "
        "<code>12-20</code> или <code>10:30-19:00</code>.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ShiftHours.hours, RoleFilter(ADMIN), TEXT_INPUT)
async def save_hours(message: Message, state: FSMContext, db: Database) -> None:
    hours = parse_time_range(message.text)
    if not hours:
        await message.answer("Не понял время. Пример: <code>12-20</code> или <code>10:30-19:00</code>.")
        return
    data = await state.get_data()
    await state.clear()
    day = date.fromisoformat(data["day"])
    await db.set_shift(data["master_id"], day, *hours)
    text, markup = await day_editor(db, day)
    await message.answer(text, reply_markup=markup)


# --- days off ----------------------------------------------------------------------------------


@router.callback_query(OffCb.filter(F.action == "list"), RoleFilter(ADMIN))
async def list_days_off(callback: CallbackQuery, db: Database, config: Config, bot: Bot) -> None:
    today = local_today(config.tz)
    days_off = await db.days_off_between(today, today + timedelta(days=60))
    await bot.send_message(chat_id(callback), render_days_off(days_off), reply_markup=days_off_kb(days_off))
    await callback.answer()


@router.callback_query(OffCb.filter(F.action == "del"), RoleFilter(ADMIN))
async def delete_day_off(
    callback: CallbackQuery, callback_data: OffCb, db: Database, config: Config, bot: Bot
) -> None:
    await db.delete_day_off(callback_data.master_id, date.fromisoformat(callback_data.day))
    today = local_today(config.tz)
    days_off = await db.days_off_between(today, today + timedelta(days=60))
    await edit_or_send(callback, bot, render_days_off(days_off), days_off_kb(days_off))
    await callback.answer("Удалено")


@router.callback_query(OffCb.filter(F.action == "add"), RoleFilter(ADMIN))
async def add_day_off_choose_master(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    masters = await db.list_masters()
    if not masters:
        await callback.answer("Сначала добавьте мастеров.", show_alert=True)
        return
    await bot.send_message(chat_id(callback), "Кому поставить выходной?", reply_markup=choose_master_kb(masters, "off"))
    await callback.answer()


async def ask_days_off(bot: Bot, chat: int, state: FSMContext, master: Master, self_request: bool) -> None:
    await state.set_state(DaysOffInput.dates)
    await state.update_data(master_id=master.id, self_request=self_request)
    who = "" if self_request else f"{escape(master.name)}: "
    await bot.send_message(
        chat,
        f"🌴 {who}напишите даты выходных, например <code>25.10</code>, "
        "<code>25.10, 27.10</code> или <code>01.11-05.11</code>.",
        reply_markup=cancel_kb(),
    )


@router.message(DaysOffInput.dates, RoleFilter(ADMIN, MASTER), TEXT_INPUT)
async def save_days_off(
    message: Message, state: FSMContext, db: Database, config: Config, bot: Bot
) -> None:
    today = local_today(config.tz)
    days = parse_dates(message.text, today, prefer="future")
    if not days:
        await message.answer(
            "Не понял даты. Примеры: <code>25.10</code>, <code>25.10, 27.10</code>, <code>01.11-05.11</code>."
        )
        return
    days = [d for d in days if d >= today]
    if not days:
        await message.answer("Эти даты уже прошли. Укажите будущие даты.")
        return
    data = await state.get_data()
    await state.clear()
    master = await _active_master(db, data["master_id"])
    if not master:
        await message.answer("Мастер удалён.")
        return
    await db.add_days_off(master.id, days)
    wanted = set(days)
    conflicts = [s.day for s in await db.shifts_between(days[0], days[-1], master.id) if s.day in wanted]
    listed = ", ".join(fmt_date(d) for d in days)
    conflict_text = (
        f"\n⚠️ {escape(master.name)}: на {', '.join(fmt_date(d) for d in conflicts)} уже стоят смены — "
        "снимите их или найдите замену." if conflicts else ""
    )
    markup = day_buttons_kb(conflicts) if conflicts else None
    if data.get("self_request"):
        await message.answer(f"🌴 Записал ваши выходные: {listed}. Администратор получит уведомление.")
        await notify_admins(
            bot, config, db, f"🌴 {escape(master.name)} просит выходные: {listed}.{conflict_text}", markup,
            exclude=message.from_user.id,
        )
    else:
        await message.answer(
            f"🌴 {escape(master.name)}: выходные {listed}. Они учтутся при составлении графика.{conflict_text}",
            reply_markup=markup,
        )
