from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .app import build_dispatcher
from .config import load_config
from .db import Database
from .reminders import reminder_loop


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    bot = Bot(config.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(config, db)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Как пользоваться"),
            BotCommand(command="cancel", description="Отменить действие"),
            BotCommand(command="id", description="Мой Telegram ID"),
        ]
    )
    reminders = asyncio.create_task(reminder_loop(bot, db, config))
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminders
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
