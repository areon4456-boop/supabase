"""What a linked master can do: see own shifts and ask for days off."""

from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..access import MASTER, RoleFilter
from ..config import Config
from ..db import Database, Master
from ..keyboards import BTN_DAY_OFF, BTN_MY_SHIFTS
from ..services import local_today
from ..views import render_master_shifts
from .schedule import ask_days_off

router = Router(name="staff")
router.message.filter(RoleFilter(MASTER))

UPCOMING_DAYS = 30


@router.message(F.text == BTN_MY_SHIFTS)
async def my_shifts(message: Message, state: FSMContext, db: Database, config: Config, me: Master) -> None:
    await state.clear()
    today = local_today(config.tz)
    shifts = await db.shifts_between(today, today + timedelta(days=UPCOMING_DAYS - 1), master_id=me.id)
    await message.answer(render_master_shifts(me, shifts, UPCOMING_DAYS))


@router.message(F.text == BTN_DAY_OFF)
async def request_day_off(message: Message, state: FSMContext, me: Master, bot: Bot) -> None:
    await state.clear()
    await ask_days_off(bot, message.chat.id, state, me, self_request=True)
