from __future__ import annotations

import asyncio
import re
from datetime import date
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..access import ADMIN, RoleFilter
from ..callbacks import CatCb, ExpCb, ReportCb
from ..charts import expenses_png
from ..config import Config
from ..db import Database
from ..excel import expenses_xlsx
from ..fmt import (
    MONTHS,
    category_label,
    fmt_date,
    fmt_day,
    fmt_money,
    month_bounds,
    month_title,
    parse_ym,
    plural,
    shift_month,
)
from ..keyboards import (
    BTN_EXPENSES,
    categories_kb,
    expense_saved_kb,
    expenses_menu_kb,
    recent_kb,
    report_kb,
)
from ..parsing import parse_expense
from ..services import local_today, month_payment_plan, monthly_totals
from ..states import AddExpense
from ..views import category_totals, render_expense_saved, render_recent, render_report
from .utils import TEXT_INPUT, chat_id, edit_or_send

router = Router(name="expenses")
router.message.filter(RoleFilter(ADMIN))
router.callback_query.filter(RoleFilter(ADMIN))

EXAMPLES = "<code>3500 краска Dynamic</code>, <code>вчера 1200 перчатки</code>, <code>05.10 60 000 аренда</code>"
QUICK_EXPENSE = F.text.regexp(r"^\s*(\d|сегодня|вчера|позавчера)", flags=re.IGNORECASE)


@router.message(F.text == BTN_EXPENSES)
async def expenses_menu(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    today = local_today(config.tz)
    expenses = await db.expenses_between(*month_bounds(today.year, today.month))
    total = sum(e.amount for e in expenses)
    await message.answer(
        f"💸 <b>Расходы за {MONTHS[today.month - 1]}</b>: {fmt_money(total, config.currency)} "
        f"({plural(len(expenses), ('запись', 'записи', 'записей'))})\n\n"
        f"Чтобы записать расход, просто напишите сообщение: {EXAMPLES}.",
        reply_markup=expenses_menu_kb(today),
    )


@router.callback_query(ExpCb.filter(F.action == "add"))
async def add_expense_start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await state.set_state(AddExpense.category)
    await bot.send_message(chat_id(callback), "Выберите категорию расхода:", reply_markup=categories_kb("exp"))
    await callback.answer()


@router.message(StateFilter(None), QUICK_EXPENSE)
async def quick_expense(message: Message, state: FSMContext, config: Config) -> None:
    parsed = parse_expense(message.text, local_today(config.tz))
    if not parsed:
        await message.answer(f"Не понял сумму. Примеры: {EXAMPLES}.")
        return
    day, amount, comment = parsed
    await state.set_state(AddExpense.category)
    await state.update_data(pending={"day": day.isoformat(), "amount": amount, "comment": comment})
    details = f" · {escape(comment)}" if comment else ""
    await message.answer(
        f"💸 <b>{fmt_money(amount, config.currency)}</b> · {fmt_day(day)}{details}\nКакая категория?",
        reply_markup=categories_kb("exp"),
    )


@router.callback_query(CatCb.filter(F.flow == "exp"), AddExpense.category)
async def expense_category(
    callback: CallbackQuery, callback_data: CatCb, state: FSMContext, db: Database, config: Config, bot: Bot
) -> None:
    pending = (await state.get_data()).get("pending")
    if pending:
        await state.clear()
        await _save(
            callback, bot, db, config, callback_data.code,
            date.fromisoformat(pending["day"]), pending["amount"], pending["comment"],
        )
        await callback.answer()
        return
    await state.set_state(AddExpense.amount)
    await state.update_data(category=callback_data.code)
    await edit_or_send(
        callback, bot,
        f"{category_label(callback_data.code)}\nНапишите сумму и, если нужно, комментарий и дату: {EXAMPLES}.",
    )
    await callback.answer()


@router.callback_query(CatCb.filter(F.flow == "exp"))
async def expense_category_stale(callback: CallbackQuery) -> None:
    await callback.answer("Эта кнопка устарела — начните заново.", show_alert=True)


@router.message(AddExpense.amount, TEXT_INPUT)
async def expense_amount(message: Message, state: FSMContext, db: Database, config: Config, bot: Bot) -> None:
    parsed = parse_expense(message.text, local_today(config.tz))
    if not parsed:
        await message.answer(f"Не понял сумму. Примеры: {EXAMPLES}.")
        return
    category = (await state.get_data())["category"]
    await state.clear()
    day, amount, comment = parsed
    expense_id = await db.add_expense(day, category, amount, comment, created_by=message.from_user.id)
    expense = await db.get_expense(expense_id)
    await message.answer(render_expense_saved(expense, config.currency), reply_markup=expense_saved_kb(expense_id))


async def _save(
    callback: CallbackQuery, bot: Bot, db: Database, config: Config,
    category: str, day: date, amount: int, comment: str,
) -> None:
    expense_id = await db.add_expense(day, category, amount, comment, created_by=callback.from_user.id)
    expense = await db.get_expense(expense_id)
    await edit_or_send(callback, bot, render_expense_saved(expense, config.currency), expense_saved_kb(expense_id))


@router.callback_query(ExpCb.filter(F.action == "del"))
async def delete_expense(callback: CallbackQuery, callback_data: ExpCb, db: Database, config: Config, bot: Bot) -> None:
    expense = await db.get_expense(callback_data.id)
    if not expense or not await db.delete_expense(expense.id):
        await callback.answer("Запись уже удалена.")
        return
    await edit_or_send(
        callback, bot,
        f"🗑 Удалено: {category_label(expense.category)} — {fmt_money(expense.amount, config.currency)} "
        f"({fmt_date(expense.day)})",
    )
    await callback.answer("Удалено")


async def recent_view(db: Database, config: Config):
    expenses = await db.recent_expenses(10)
    buttons = [
        (e.id, f"{fmt_date(e.day)} · {fmt_money(e.amount, config.currency)} · {category_label(e.category)}")
        for e in expenses
    ]
    return render_recent(expenses, config.currency), recent_kb(buttons)


@router.callback_query(ExpCb.filter(F.action == "recent"))
async def recent(callback: CallbackQuery, db: Database, config: Config, bot: Bot) -> None:
    text, markup = await recent_view(db, config)
    await bot.send_message(chat_id(callback), text, reply_markup=markup)
    await callback.answer()


@router.callback_query(ExpCb.filter(F.action == "delr"))
async def delete_from_recent(callback: CallbackQuery, callback_data: ExpCb, db: Database, config: Config, bot: Bot) -> None:
    deleted = await db.delete_expense(callback_data.id)
    text, markup = await recent_view(db, config)
    await edit_or_send(callback, bot, text, markup)
    await callback.answer("Удалено" if deleted else "Запись уже удалена")


# --- monthly report ----------------------------------------------------------------------------


@router.callback_query(ReportCb.filter(F.action == "show"))
async def report(callback: CallbackQuery, callback_data: ReportCb, db: Database, config: Config, bot: Bot) -> None:
    year, month = parse_ym(callback_data.ym)
    prev_y, prev_m = shift_month(year, month, -1)
    text = render_report(
        year,
        month,
        await db.expenses_between(*month_bounds(year, month)),
        await db.total_between(*month_bounds(prev_y, prev_m)),
        prev_m,
        await month_payment_plan(db, year, month),
        config.currency,
    )
    await edit_or_send(callback, bot, text, report_kb(year, month))
    await callback.answer()


@router.callback_query(ReportCb.filter(F.action == "chart"))
async def report_chart(callback: CallbackQuery, callback_data: ReportCb, db: Database, config: Config, bot: Bot) -> None:
    year, month = parse_ym(callback_data.ym)
    totals = category_totals(await db.expenses_between(*month_bounds(year, month)))
    history = await monthly_totals(db, year, month)
    png = await asyncio.to_thread(expenses_png, year, month, totals, history, config.currency)
    await bot.send_photo(
        chat_id(callback),
        BufferedInputFile(png, filename=f"rashody-{callback_data.ym}.png"),
        caption=f"📈 Расходы · {month_title(year, month)}",
    )
    await callback.answer()


@router.callback_query(ReportCb.filter(F.action == "xlsx"))
async def report_excel(callback: CallbackQuery, callback_data: ReportCb, db: Database, config: Config, bot: Bot) -> None:
    year, month = parse_ym(callback_data.ym)
    data = await asyncio.to_thread(
        expenses_xlsx,
        year,
        month,
        await db.expenses_between(*month_bounds(year, month)),
        await month_payment_plan(db, year, month),
        local_today(config.tz),
    )
    await bot.send_document(
        chat_id(callback),
        BufferedInputFile(data, filename=f"rashody-{callback_data.ym}.xlsx"),
        caption=f"📤 Расходы · {month_title(year, month)}",
    )
    await callback.answer()
