"""Daily digest: tomorrow's shifts and upcoming payments to admins, shift reminders to masters."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot

from .access import admin_ids
from .config import Config
from .db import Database
from .fmt import fmt_day
from .services import due_soon
from .views import render_tomorrow_digest

log = logging.getLogger(__name__)
CHECK_EVERY_SECONDS = 30


async def send_daily(bot: Bot, db: Database, config: Config, today: date) -> None:
    tomorrow = today + timedelta(days=1)
    shifts = await db.shifts_between(tomorrow, tomorrow)
    due = await due_soon(db, today)

    digest = render_tomorrow_digest(tomorrow, shifts, due, today, config.currency)
    if digest:
        for admin_id in await admin_ids(config, db):
            await _safe_send(bot, admin_id, digest)

    masters = {m.id: m for m in await db.list_masters()}
    for shift in shifts:
        master = masters.get(shift.master_id)
        if master and master.telegram_id:
            await _safe_send(
                bot,
                master.telegram_id,
                f"⏰ Напоминание: завтра, {fmt_day(tomorrow)}, у вас смена {shift.start}–{shift.end}.",
            )


async def _safe_send(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception:  # noqa: BLE001 - a blocked chat must not stop the rest of the digest
        log.warning("Could not deliver reminder to %s", chat_id, exc_info=True)


async def reminder_loop(bot: Bot, db: Database, config: Config) -> None:
    while True:
        try:
            now = datetime.now(config.tz)
            settings = await db.get_settings()
            today = now.date().isoformat()
            if (
                settings.reminders_on
                and now.strftime("%H:%M") >= settings.reminder_time
                and settings.last_reminder_day != today
            ):
                # Mark first so a failure never turns into a reminder storm.
                await db.set_setting("last_reminder_day", today)
                await send_daily(bot, db, config, now.date())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Reminder loop iteration failed")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
