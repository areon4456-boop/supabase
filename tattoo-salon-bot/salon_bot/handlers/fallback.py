"""Registered last: whatever no other handler took."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from ..access import ADMIN, GUEST

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, role: str) -> None:
    if role == GUEST:
        await message.answer(
            f"Доступ есть только у сотрудников салона. Ваш ID: <code>{message.from_user.id}</code>."
        )
    elif role == ADMIN:
        await message.answer(
            "Не понял 🤔 Пользуйтесь кнопками меню. Чтобы записать расход, напишите, например, "
            "<code>3500 краска</code>. Справка — /help."
        )
    else:
        await message.answer("Не понял 🤔 Пользуйтесь кнопками меню. Справка — /help.")


@router.callback_query()
async def unknown_callback(callback: CallbackQuery, role: str) -> None:
    text = "Нет доступа." if role == GUEST else "Эта кнопка устарела — откройте раздел заново."
    await callback.answer(text, show_alert=True)
