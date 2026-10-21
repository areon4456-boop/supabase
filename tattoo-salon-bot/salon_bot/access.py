"""Roles: the owner/admins manage everything, linked masters see the schedule, everyone else is a guest."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.types import TelegramObject, User

from .config import Config
from .db import Database

ADMIN, MASTER, GUEST = "admin", "master", "guest"


async def admin_ids(config: Config, db: Database) -> set[int]:
    return set(config.admin_ids) | await db.db_admins()


class RoleMiddleware(BaseMiddleware):
    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        role, me = GUEST, None
        if user is not None:
            me = await self.db.master_by_telegram(user.id)
            if user.id in await admin_ids(self.config, self.db):
                role = ADMIN
            elif me is not None:
                role = MASTER
        data["role"] = role
        data["me"] = me
        return await handler(event, data)


class RoleFilter(Filter):
    def __init__(self, *roles: str) -> None:
        self.roles = roles

    async def __call__(self, event: TelegramObject, role: str = GUEST) -> bool:
        return role in self.roles
