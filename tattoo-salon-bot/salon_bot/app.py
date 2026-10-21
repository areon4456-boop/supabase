from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .access import RoleMiddleware
from .config import Config
from .db import Database
from .handlers import common, expenses, fallback, masters, payments, schedule, settings, staff


def build_dispatcher(config: Config, db: Database) -> Dispatcher:
    # `config` and `db` become handler arguments via the dispatcher's workflow data.
    dp = Dispatcher(storage=MemoryStorage(), config=config, db=db)
    role_middleware = RoleMiddleware(config, db)
    dp.message.outer_middleware(role_middleware)
    dp.callback_query.outer_middleware(role_middleware)
    # Order matters: commands and menu buttons first, the catch-all router last.
    dp.include_routers(
        common.router,
        schedule.router,
        staff.router,
        masters.router,
        expenses.router,
        payments.router,
        settings.router,
        fallback.router,
    )
    return dp
