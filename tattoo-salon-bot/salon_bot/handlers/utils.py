from __future__ import annotations

from aiogram import Bot, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message

from ..access import admin_ids
from ..config import Config
from ..db import Database
from ..keyboards import ADMIN_BUTTONS, BTN_CANCEL, STAFF_BUTTONS

# Free-text answers inside a dialog: anything except menu buttons and commands,
# so pressing a menu button always leaves the current dialog.
TEXT_INPUT = F.text & ~F.text.in_(ADMIN_BUTTONS | STAFF_BUTTONS | {BTN_CANCEL}) & ~F.text.startswith("/")


def chat_id(callback: CallbackQuery) -> int:
    return callback.message.chat.id if callback.message else callback.from_user.id


async def edit_or_send(
    callback: CallbackQuery, bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    """Replace the text of the message the button belongs to, or send a new one if that is impossible."""
    message = callback.message
    if isinstance(message, Message) and message.text is not None:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return
    await bot.send_message(chat_id(callback), text, reply_markup=markup)


async def send_photo(
    callback: CallbackQuery, bot: Bot, png: bytes, filename: str, caption: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    await bot.send_photo(
        chat_id(callback), BufferedInputFile(png, filename=filename), caption=caption, reply_markup=markup
    )


async def notify_admins(
    bot: Bot, config: Config, db: Database, text: str, markup: InlineKeyboardMarkup | None = None,
    exclude: int | None = None,
) -> None:
    for admin_id in await admin_ids(config, db):
        if admin_id == exclude:
            continue
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception:  # noqa: BLE001 - an admin who blocked the bot must not break the flow
            continue
