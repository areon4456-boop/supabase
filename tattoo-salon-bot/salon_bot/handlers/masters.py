from __future__ import annotations

import secrets
from collections import Counter
from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from ..access import ADMIN, RoleFilter
from ..callbacks import MasterCb
from ..config import Config
from ..db import Database
from ..fmt import month_bounds
from ..keyboards import BTN_MASTERS, cancel_kb, confirm_delete_master_kb, master_card_kb, masters_kb
from ..services import local_today
from ..states import MasterInput
from ..views import render_master_card, render_masters
from .schedule import ask_days_off
from .utils import TEXT_INPUT, chat_id, edit_or_send

router = Router(name="masters")
router.message.filter(RoleFilter(ADMIN))
router.callback_query.filter(RoleFilter(ADMIN))

MAX_NAME = 40


async def masters_view(db: Database, config: Config):
    today = local_today(config.tz)
    masters = await db.list_masters()
    counts = Counter(s.master_id for s in await db.shifts_between(*month_bounds(today.year, today.month)))
    return render_masters(masters, counts, today.year, today.month), masters_kb(masters)


async def card_view(db: Database, config: Config, master_id: int):
    master = await db.get_master(master_id)
    if not master or not master.active:
        return None
    today = local_today(config.tz)
    days_off = [o for o in await db.days_off_between(today, today + timedelta(days=60)) if o.master_id == master_id]
    return render_master_card(master, days_off), master_card_kb(master)


@router.message(F.text == BTN_MASTERS)
async def show_masters(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    text, markup = await masters_view(db, config)
    await message.answer(text, reply_markup=markup)


@router.callback_query(MasterCb.filter(F.action == "list"))
async def list_masters(callback: CallbackQuery, db: Database, config: Config, bot: Bot) -> None:
    text, markup = await masters_view(db, config)
    await edit_or_send(callback, bot, text, markup)
    await callback.answer()


@router.callback_query(MasterCb.filter(F.action == "add"))
async def ask_names(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(MasterInput.names)
    await bot.send_message(
        chat_id(callback),
        "Напишите имена мастеров — каждое с новой строки. Например:\n<code>Аня\nОлег\nКатя</code>",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(MasterInput.names, TEXT_INPUT)
async def save_names(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    names = [n.strip()[:MAX_NAME] for n in message.text.replace(",", "\n").splitlines() if n.strip()]
    if not names:
        await message.answer("Напишите хотя бы одно имя.")
        return
    await state.clear()
    for name in names:
        await db.add_master(name)
    text, markup = await masters_view(db, config)
    await message.answer(f"✅ Добавлено: {escape(', '.join(names))}\n\n{text}", reply_markup=markup)


@router.callback_query(MasterCb.filter(F.action == "open"))
async def open_master(callback: CallbackQuery, callback_data: MasterCb, db: Database, config: Config, bot: Bot) -> None:
    view = await card_view(db, config, callback_data.id)
    if view is None:
        await callback.answer("Мастер удалён.", show_alert=True)
        return
    await edit_or_send(callback, bot, *view)
    await callback.answer()


@router.callback_query(MasterCb.filter(F.action == "rename"))
async def ask_rename(callback: CallbackQuery, callback_data: MasterCb, state: FSMContext, bot: Bot) -> None:
    await state.set_state(MasterInput.rename)
    await state.update_data(master_id=callback_data.id)
    await bot.send_message(chat_id(callback), "Новое имя мастера:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(MasterInput.rename, TEXT_INPUT)
async def save_rename(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    name = message.text.strip()[:MAX_NAME]
    if not name:
        await message.answer("Имя не может быть пустым.")
        return
    data = await state.get_data()
    await state.clear()
    await db.rename_master(data["master_id"], name)
    view = await card_view(db, config, data["master_id"])
    if view:
        await message.answer(view[0], reply_markup=view[1])


@router.callback_query(MasterCb.filter(F.action == "invite"))
async def invite(callback: CallbackQuery, callback_data: MasterCb, db: Database, bot: Bot) -> None:
    master = await db.get_master(callback_data.id)
    if not master or not master.active:
        await callback.answer("Мастер удалён.", show_alert=True)
        return
    code = secrets.token_urlsafe(9)
    await db.set_invite_code(master.id, code)
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=m{code}"
    await bot.send_message(
        chat_id(callback),
        f"🔗 Приглашение · <b>{escape(master.name)}</b>\n\n{link}\n\n"
        "Перешлите ссылку мастеру. Открыв её, он(а) увидит свой график, сможет попросить выходной "
        "и будет получать напоминания о сменах. Ссылка одноразовая.",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()


@router.callback_query(MasterCb.filter(F.action == "unlink"))
async def unlink(callback: CallbackQuery, callback_data: MasterCb, db: Database, config: Config, bot: Bot) -> None:
    await db.unlink_telegram(callback_data.id)
    view = await card_view(db, config, callback_data.id)
    if view:
        await edit_or_send(callback, bot, *view)
    await callback.answer("Мастер отключён от бота")


@router.callback_query(MasterCb.filter(F.action == "off"))
async def master_day_off(callback: CallbackQuery, callback_data: MasterCb, state: FSMContext, db: Database, bot: Bot) -> None:
    master = await db.get_master(callback_data.id)
    if not master or not master.active:
        await callback.answer("Мастер удалён.", show_alert=True)
        return
    await ask_days_off(bot, chat_id(callback), state, master, self_request=False)
    await callback.answer()


@router.callback_query(MasterCb.filter(F.action == "delete"))
async def ask_delete(callback: CallbackQuery, callback_data: MasterCb, db: Database, bot: Bot) -> None:
    master = await db.get_master(callback_data.id)
    if not master or not master.active:
        await callback.answer("Мастер уже удалён.", show_alert=True)
        return
    await edit_or_send(
        callback,
        bot,
        f"Удалить мастера <b>{escape(master.name)}</b>? Будущие смены и выходные будут сняты, прошлые останутся в истории.",
        confirm_delete_master_kb(master),
    )
    await callback.answer()


@router.callback_query(MasterCb.filter(F.action == "delok"))
async def delete_master(callback: CallbackQuery, callback_data: MasterCb, db: Database, config: Config, bot: Bot) -> None:
    await db.deactivate_master(callback_data.id, local_today(config.tz))
    text, markup = await masters_view(db, config)
    await edit_or_send(callback, bot, text, markup)
    await callback.answer("Мастер удалён")
