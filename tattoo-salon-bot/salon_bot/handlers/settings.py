from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..access import ADMIN, RoleFilter
from ..callbacks import SetCb
from ..db import Database
from ..keyboards import BTN_SETTINGS, cancel_kb, numbers_kb, settings_kb, weekdays_toggle_kb
from ..parsing import parse_time, parse_time_range
from ..states import SettingsInput
from ..views import render_settings
from .utils import TEXT_INPUT, chat_id, edit_or_send

router = Router(name="settings")
router.message.filter(RoleFilter(ADMIN))
router.callback_query.filter(RoleFilter(ADMIN))

NOTE = "\n\nИзменения применятся при следующем «⚡ Составить»."
PER_DAY_CHOICES = [(n, str(n)) for n in range(1, 7)]
STREAK_CHOICES = [(n, str(n)) for n in range(2, 8)] + [(31, "∞")]


async def settings_view(db: Database):
    settings = await db.get_settings()
    return render_settings(settings) + NOTE, settings_kb(settings)


@router.message(F.text == BTN_SETTINGS)
async def show_settings(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    text, markup = await settings_view(db)
    await message.answer(text, reply_markup=markup)


@router.callback_query(SetCb.filter(F.action == "show"))
async def back_to_settings(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    await edit_or_send(callback, bot, *await settings_view(db))
    await callback.answer()


@router.callback_query(SetCb.filter(F.action == "days"))
async def choose_days(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    settings = await db.get_settings()
    await edit_or_send(callback, bot, "📆 В какие дни салон работает?", weekdays_toggle_kb(settings.open_weekdays))
    await callback.answer()


@router.callback_query(SetCb.filter(F.action == "day"))
async def toggle_day(callback: CallbackQuery, callback_data: SetCb, db: Database, bot: Bot) -> None:
    days = set((await db.get_settings()).open_weekdays)
    days ^= {callback_data.value}
    if not days:
        await callback.answer("Хотя бы один день должен быть рабочим.", show_alert=True)
        return
    await db.set_setting("open_weekdays", ",".join(str(d) for d in sorted(days)))
    await edit_or_send(callback, bot, "📆 В какие дни салон работает?", weekdays_toggle_kb(days))
    await callback.answer()


@router.callback_query(SetCb.filter(F.action == "perday"))
async def choose_per_day(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    settings = await db.get_settings()
    await edit_or_send(
        callback, bot, "👥 Сколько мастеров должно работать в смену?",
        numbers_kb("perdayset", PER_DAY_CHOICES, settings.per_day),
    )
    await callback.answer()


@router.callback_query(SetCb.filter(F.action == "streak"))
async def choose_streak(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    settings = await db.get_settings()
    await edit_or_send(
        callback, bot, "🔁 Сколько дней подряд мастер может работать без выходного?",
        numbers_kb("streakset", STREAK_CHOICES, settings.max_streak),
    )
    await callback.answer()


@router.callback_query(SetCb.filter(F.action.in_({"perdayset", "streakset"})))
async def save_number(callback: CallbackQuery, callback_data: SetCb, db: Database, bot: Bot) -> None:
    key = "per_day" if callback_data.action == "perdayset" else "max_streak"
    await db.set_setting(key, str(callback_data.value))
    await edit_or_send(callback, bot, *await settings_view(db))
    await callback.answer("Сохранено")


@router.callback_query(SetCb.filter(F.action == "remtoggle"))
async def toggle_reminders(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    settings = await db.get_settings()
    await db.set_setting("reminders_on", "0" if settings.reminders_on else "1")
    await edit_or_send(callback, bot, *await settings_view(db))
    await callback.answer()


@router.callback_query(SetCb.filter(F.action == "hours"))
async def ask_hours(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(SettingsInput.hours)
    await bot.send_message(
        chat_id(callback), "🕐 Часы смены по умолчанию, например <code>11-21</code>:", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(SettingsInput.hours, TEXT_INPUT)
async def save_hours(message: Message, state: FSMContext, db: Database) -> None:
    hours = parse_time_range(message.text)
    if not hours:
        await message.answer("Не понял. Пример: <code>11-21</code> или <code>10:30-20:00</code>.")
        return
    await state.clear()
    await db.set_setting("day_start", hours[0])
    await db.set_setting("day_end", hours[1])
    text, markup = await settings_view(db)
    await message.answer(text, reply_markup=markup)


@router.callback_query(SetCb.filter(F.action == "remtime"))
async def ask_reminder_time(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(SettingsInput.reminder_time)
    await bot.send_message(
        chat_id(callback),
        "⏰ Во сколько присылать ежедневные напоминания о сменах и платежах? Например <code>10:00</code>.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsInput.reminder_time, TEXT_INPUT)
async def save_reminder_time(message: Message, state: FSMContext, db: Database) -> None:
    value = parse_time(message.text)
    if not value or value == "24:00":
        await message.answer("Не понял время. Пример: <code>10:00</code>.")
        return
    await state.clear()
    await db.set_setting("reminder_time", value)
    text, markup = await settings_view(db)
    await message.answer(text, reply_markup=markup)
