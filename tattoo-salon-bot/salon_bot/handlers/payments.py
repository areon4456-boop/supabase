"""The expense schedule: recurring and one-off payments with due dates."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..access import ADMIN, RoleFilter
from ..callbacks import CatCb, PayCb, PeriodCb, WeekdayCb
from ..config import Config
from ..db import Database
from ..fmt import category_label, fmt_money, parse_ym
from ..keyboards import (
    BTN_PAYMENTS,
    cancel_kb,
    categories_kb,
    payments_kb,
    period_kb,
    planned_list_kb,
    weekday_kb,
)
from ..parsing import parse_amount, parse_date
from ..payments import occurrences
from ..services import local_today, month_payment_plan
from ..states import AddPlanned
from ..views import render_payments, render_planned_list
from .utils import TEXT_INPUT, chat_id, edit_or_send

router = Router(name="payments")
router.message.filter(RoleFilter(ADMIN))
router.callback_query.filter(RoleFilter(ADMIN))

MAX_TITLE = 40


async def payments_view(db: Database, config: Config, year: int, month: int):
    plan = await month_payment_plan(db, year, month)
    today = local_today(config.tz)
    return render_payments(year, month, plan, today, config.currency), payments_kb(year, month, plan)


@router.message(F.text == BTN_PAYMENTS)
async def show_payments(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    today = local_today(config.tz)
    text, markup = await payments_view(db, config, today.year, today.month)
    await message.answer(text, reply_markup=markup)


@router.callback_query(PayCb.filter(F.action == "month"))
async def payments_month(callback: CallbackQuery, callback_data: PayCb, db: Database, config: Config, bot: Bot) -> None:
    text, markup = await payments_view(db, config, *parse_ym(callback_data.ym))
    await edit_or_send(callback, bot, text, markup)
    await callback.answer()


@router.callback_query(PayCb.filter(F.action == "pay"))
async def mark_paid(callback: CallbackQuery, callback_data: PayCb, db: Database, config: Config, bot: Bot) -> None:
    planned = await db.get_planned(callback_data.id)
    if not planned:
        await callback.answer("Этот платёж удалён из графика.", show_alert=True)
        return
    due = date.fromisoformat(callback_data.due)
    try:
        await db.add_expense(
            local_today(config.tz), planned.category, planned.amount, planned.title,
            created_by=callback.from_user.id, planned_id=planned.id, due_day=due,
        )
        note = f"✅ {planned.title}: {fmt_money(planned.amount, config.currency)} записано в расходы"
    except sqlite3.IntegrityError:
        note = "Этот платёж уже отмечен как оплаченный."
    text, markup = await payments_view(db, config, *parse_ym(callback_data.ym))
    await edit_or_send(callback, bot, text, markup)
    await callback.answer(note)


@router.callback_query(PayCb.filter(F.action == "list"))
async def list_planned(callback: CallbackQuery, db: Database, config: Config, bot: Bot) -> None:
    plans = await db.list_planned()
    await bot.send_message(
        chat_id(callback), render_planned_list(plans, config.currency), reply_markup=planned_list_kb(plans)
    )
    await callback.answer()


@router.callback_query(PayCb.filter(F.action == "del"))
async def delete_planned(callback: CallbackQuery, callback_data: PayCb, db: Database, config: Config, bot: Bot) -> None:
    await db.deactivate_planned(callback_data.id)
    plans = await db.list_planned()
    await edit_or_send(callback, bot, render_planned_list(plans, config.currency), planned_list_kb(plans))
    await callback.answer("Платёж убран из графика")


# --- new planned payment dialog --------------------------------------------------------------


@router.callback_query(PayCb.filter(F.action == "new"))
async def new_planned(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await state.set_state(AddPlanned.title)
    await bot.send_message(
        chat_id(callback),
        "Как назвать платёж? Например: <code>Аренда</code>, <code>Интернет</code>, <code>Закупка игл</code>.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AddPlanned.title, TEXT_INPUT)
async def planned_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()[:MAX_TITLE]
    await state.update_data(title=title)
    await state.set_state(AddPlanned.category)
    await message.answer(f"«{escape(title)}» — какая категория?", reply_markup=categories_kb("plan"))


@router.callback_query(CatCb.filter(F.flow == "plan"), AddPlanned.category)
async def planned_category(callback: CallbackQuery, callback_data: CatCb, state: FSMContext, bot: Bot) -> None:
    await state.update_data(category=callback_data.code)
    await state.set_state(AddPlanned.amount)
    await edit_or_send(callback, bot, f"{category_label(callback_data.code)}\nСумма платежа? Например: <code>60000</code>.")
    await callback.answer()


@router.message(AddPlanned.amount, TEXT_INPUT)
async def planned_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text)
    if not amount:
        await message.answer("Не понял сумму. Пример: <code>60000</code> или <code>60 000</code>.")
        return
    await state.update_data(amount=amount)
    await state.set_state(AddPlanned.period)
    await message.answer("Как часто платить?", reply_markup=period_kb())


@router.callback_query(PeriodCb.filter(), AddPlanned.period)
async def planned_period(callback: CallbackQuery, callback_data: PeriodCb, state: FSMContext, bot: Bot) -> None:
    await state.update_data(period=callback_data.period)
    if callback_data.period == "monthly":
        await state.set_state(AddPlanned.month_day)
        await edit_or_send(callback, bot, "Какого числа платить? Напишите число от 1 до 31.")
    elif callback_data.period == "weekly":
        await state.set_state(AddPlanned.weekday)
        await edit_or_send(callback, bot, "В какой день недели?", weekday_kb())
    else:
        await state.set_state(AddPlanned.once_day)
        await edit_or_send(callback, bot, "Когда платить? Напишите дату, например <code>15.11</code>.")
    await callback.answer()


@router.message(AddPlanned.month_day, TEXT_INPUT)
async def planned_month_day(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    text = message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 31:
        await message.answer("Напишите число от 1 до 31.")
        return
    await _save(message, state, db, config, day=int(text), once_day=None)


@router.callback_query(WeekdayCb.filter(), AddPlanned.weekday)
async def planned_weekday(
    callback: CallbackQuery, callback_data: WeekdayCb, state: FSMContext, db: Database, config: Config
) -> None:
    await callback.answer()
    await _save(callback.message, state, db, config, day=callback_data.day, once_day=None)


@router.message(AddPlanned.once_day, TEXT_INPUT)
async def planned_once_day(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    day = parse_date(message.text, local_today(config.tz), prefer="future")
    if not day:
        await message.answer("Не понял дату. Пример: <code>15.11</code>.")
        return
    await _save(message, state, db, config, day=None, once_day=day)


async def _save(
    message: Message, state: FSMContext, db: Database, config: Config, day: int | None, once_day: date | None
) -> None:
    data = await state.get_data()
    await state.clear()
    today = local_today(config.tz)
    planned_id = await db.add_planned(
        data["title"], data["category"], data["amount"], data["period"], day, once_day, start_day=today
    )
    planned = await db.get_planned(planned_id)
    upcoming = occurrences(planned, today, today + timedelta(days=366))
    first_due = upcoming[0] if upcoming else today
    year, month = first_due.year, first_due.month
    text, markup = await payments_view(db, config, year, month)
    await message.answer(
        f"✅ Добавлен платёж «{escape(planned.title)}» — {fmt_money(planned.amount, config.currency)}, "
        f"{planned.describe()}. Напомню о нём заранее.\n\n{text}",
        reply_markup=markup,
    )

