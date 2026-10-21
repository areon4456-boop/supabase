"""End-to-end dialogs through the real dispatcher with a fake Telegram API session."""

from __future__ import annotations

import itertools
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from salon_bot.app import build_dispatcher
from salon_bot.callbacks import CatCb, DayCb, ExpCb, MasterCb, MonthCb, PayCb, PeriodCb, ReportCb, SetCb
from salon_bot.config import Config
from salon_bot.db import Database
from salon_bot.fmt import month_bounds, shift_month, ym
from salon_bot.reminders import send_daily
from salon_bot.services import local_today

OWNER, MASTER_USER, STRANGER = 100, 200, 300
TZ = ZoneInfo("Europe/Moscow")


class FakeSession(BaseSession):
    """Records every Bot API call and returns minimal plausible results."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list = []
        self.ids = itertools.count(1000)

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=42, is_bot=True, first_name="Salon", username="salon_test_bot")
        if name.startswith(("Send", "Edit")):
            return Message(
                message_id=next(self.ids),
                date=datetime.now(),
                chat=Chat(id=getattr(method, "chat_id", None) or 1, type="private"),
                text=getattr(method, "text", None),
            )
        return True


class Harness:
    def __init__(self, dp, bot: Bot, session: FakeSession) -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self.ids = itertools.count(1)

    def _user(self, user_id: int) -> User:
        return User(id=user_id, is_bot=False, first_name=f"user{user_id}")

    async def send(self, user_id: int, text: str) -> list:
        start = len(self.session.requests)
        message = Message(
            message_id=next(self.ids), date=datetime.now(), chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id), text=text,
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(self.ids), message=message))
        return self.session.requests[start:]

    async def press(self, user_id: int, data, text: str = "…") -> list:
        start = len(self.session.requests)
        message = Message(
            message_id=next(self.ids), date=datetime.now(), chat=Chat(id=user_id, type="private"),
            from_user=User(id=42, is_bot=True, first_name="Salon"), text=text,
        )
        callback = CallbackQuery(
            id=str(next(self.ids)), from_user=self._user(user_id), chat_instance="test",
            data=data if isinstance(data, str) else data.pack(), message=message,
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(self.ids), callback_query=callback))
        return self.session.requests[start:]


def texts(requests) -> str:
    """Everything the bot said: message texts, captions and callback alerts."""
    parts = []
    for r in requests:
        for attr in ("text", "caption"):
            value = getattr(r, attr, None)
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def kinds(requests) -> list[str]:
    return [type(r).__name__ for r in requests]


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "salon.db")
    await db.connect()
    config = Config(token="42:TEST", admin_ids=frozenset(), db_path=tmp_path / "salon.db", tz=TZ, currency="₽")
    session = FakeSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    harness = Harness(build_dispatcher(config, db), bot, session)
    yield harness, db, config
    await db.close()


async def test_full_owner_and_master_flow(env):
    h, db, config = env
    today = local_today(TZ)
    next_y, next_m = shift_month(today.year, today.month, 1)
    next_ym = ym(next_y, next_m)

    # First user becomes the owner.
    out = await h.send(OWNER, "/start")
    assert "владельцем" in texts(out)

    # Strangers get no access.
    out = await h.send(STRANGER, "покажи график")
    assert "только у сотрудников" in texts(out)

    # Masters.
    out = await h.send(OWNER, "👥 Мастера")
    assert "Пока никого нет" in texts(out)
    await h.press(OWNER, MasterCb(action="add"))
    out = await h.send(OWNER, "Аня\nОлег\nКатя")
    assert "Добавлено: Аня, Олег, Катя" in texts(out)
    masters = await db.list_masters()
    assert [m.name for m in masters] == ["Аня", "Олег", "Катя"]
    anya, oleg, katya = masters

    # A requested day off is respected by the planner.
    day_off = datetime(next_y, next_m, 10).date()
    await h.press(OWNER, MasterCb(action="off", id=katya.id))
    out = await h.send(OWNER, day_off.strftime("%d.%m.%Y"))
    assert "Катя: выходные" in texts(out)

    # Automatic schedule for next month.
    out = await h.send(OWNER, "📅 График работы")
    assert "График" in texts(out)
    out = await h.press(OWNER, MonthCb(action="gen", ym=next_ym))
    assert "составлен" in texts(out)
    assert "SendPhoto" in kinds(out)
    first, last = month_bounds(next_y, next_m)
    shifts = await db.shifts_between(first, last)
    assert len(shifts) == 2 * (last.day)  # every day open, 2 masters per day by default
    assert not any(s.master_id == katya.id and s.day == day_off for s in shifts)

    # Regenerating asks for confirmation first.
    out = await h.press(OWNER, MonthCb(action="gen", ym=next_ym))
    assert "Составить график заново?" in texts(out)
    out = await h.press(OWNER, MonthCb(action="genok", ym=next_ym))
    assert "составлен" in texts(out)

    # Day editor: toggle a shift and change hours.
    day = first + timedelta(days=2)
    working = {s.master_id for s in await db.shifts_between(day, day)}
    target = next(m for m in masters if m.id not in working)
    out = await h.press(OWNER, DayCb(action="toggle", day=day.isoformat(), master_id=target.id))
    assert f"✅ {target.name}" in texts(out)
    await h.press(OWNER, DayCb(action="hours", day=day.isoformat(), master_id=target.id))
    out = await h.send(OWNER, "12-20")
    assert f"{target.name} 12:00–20:00" in texts(out)

    # Month picture and Excel.
    assert "SendPhoto" in kinds(await h.press(OWNER, MonthCb(action="img", ym=next_ym)))
    assert "SendDocument" in kinds(await h.press(OWNER, MonthCb(action="xlsx", ym=next_ym)))

    # Quick expense: amount first, category second.
    out = await h.send(OWNER, "3 500 краска Dynamic")
    assert "Какая категория?" in texts(out)
    out = await h.press(OWNER, CatCb(flow="exp", code="supplies"))
    assert "Записал" in texts(out)
    # Guided expense: category first, then amount with a date.
    await h.press(OWNER, ExpCb(action="add"))
    await h.press(OWNER, CatCb(flow="exp", code="rent"))
    await h.send(OWNER, "вчера 60000 аренда")
    expenses = await db.recent_expenses()
    assert {(e.category, e.amount, e.comment) for e in expenses} == {
        ("supplies", 350_000, "краска Dynamic"),
        ("rent", 6_000_000, "аренда"),
    }

    # Report, chart and Excel for the current month.
    month = ym(today.year, today.month)
    out = await h.press(OWNER, ReportCb(action="show", ym=month))
    assert "Итого" in texts(out) or (today.day == 1 and "Расходов за этот месяц нет" in texts(out))
    assert "SendPhoto" in kinds(await h.press(OWNER, ReportCb(action="chart", ym=month)))
    assert "SendDocument" in kinds(await h.press(OWNER, ReportCb(action="xlsx", ym=month)))

    # A menu button in the middle of a dialog leaves the dialog.
    await h.press(OWNER, PayCb(action="new"))
    out = await h.send(OWNER, "💸 Расходы")
    assert "Чтобы записать расход" in texts(out)

    # Payment schedule: monthly rent on the 1st, then mark it paid.
    await h.press(OWNER, PayCb(action="new"))
    await h.send(OWNER, "Аренда")
    await h.press(OWNER, CatCb(flow="plan", code="rent"))
    await h.send(OWNER, "60 000")
    await h.press(OWNER, PeriodCb(period="monthly"))
    out = await h.send(OWNER, "1")
    assert "Добавлен платёж «Аренда»" in texts(out)
    planned = (await db.list_planned())[0]
    due = datetime(next_y, next_m, 1).date()
    out = await h.press(OWNER, PayCb(action="month", ym=next_ym))
    assert "⏳" in texts(out)
    await h.press(OWNER, PayCb(action="pay", ym=next_ym, id=planned.id, due=due.isoformat()))
    assert (planned.id, due) in await db.paid_occurrences(due, due)
    out = await h.press(OWNER, PayCb(action="pay", ym=next_ym, id=planned.id, due=due.isoformat()))
    answers = [r for r in out if type(r).__name__ == "AnswerCallbackQuery"]
    assert "уже отмечен" in answers[0].text

    # Settings.
    await h.press(OWNER, SetCb(action="perdayset", value=3))
    assert (await db.get_settings()).per_day == 3

    # Invite a master and let them use their menu.
    out = await h.press(OWNER, MasterCb(action="invite", id=anya.id))
    code = re.search(r"start=(m[\w-]+)", texts(out))[1]
    out = await h.send(MASTER_USER, f"/start {code}")
    assert "Привет, Аня" in texts(out)
    assert any(getattr(r, "chat_id", None) == OWNER and "подключился" in r.text for r in out if hasattr(r, "text"))
    out = await h.send(MASTER_USER, "📅 Мои смены")
    assert "Аня" in texts(out)
    # Masters cannot reach admin sections.
    out = await h.send(MASTER_USER, "💸 Расходы")
    assert "Чтобы записать расход" not in texts(out)

    await h.send(MASTER_USER, "🌴 Хочу выходной")
    wish = first + timedelta(days=20)
    out = await h.send(MASTER_USER, wish.strftime("%d.%m.%Y"))
    assert "Записал ваши выходные" in texts(out)
    assert any(getattr(r, "chat_id", None) == OWNER and "просит выходные" in r.text for r in out if hasattr(r, "text"))

    # Daily reminders: owner digest and the master's own shift.
    tomorrow = today + timedelta(days=1)
    await db.set_shift(anya.id, tomorrow, "11:00", "21:00")
    start = len(h.session.requests)
    await send_daily(h.bot, db, config, today)
    sent = h.session.requests[start:]
    assert any(r.chat_id == OWNER and "Завтра" in r.text for r in sent)
    assert any(r.chat_id == MASTER_USER and "у вас смена" in r.text for r in sent)
