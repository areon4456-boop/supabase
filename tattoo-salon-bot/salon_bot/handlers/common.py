from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..access import ADMIN, GUEST, MASTER, admin_ids
from ..config import Config
from ..db import Database
from ..keyboards import BTN_CANCEL, admin_menu, staff_menu
from .utils import notify_admins

router = Router(name="common")

HELP_ADMIN = """<b>Как пользоваться</b>

<b>📅 График работы</b> — смены мастеров по неделям. «⚡ Составить» распределяет смены на месяц автоматически: поровну, с учётом выходных мастеров, рабочих дней салона и лимита дней подряд. «✏️ день» — поставить или снять смену, поменять часы.

<b>💸 Расходы</b> — просто напишите сообщение:
<code>3500 краска Dynamic</code>
<code>вчера 1200 перчатки</code>
<code>05.10 60 000 аренда</code>
и выберите категорию. Там же — отчёт за месяц, диаграмма и Excel.

<b>🗓 Платежи</b> — график затрат: аренда, коммуналка, реклама, закупки. Бот покажет, что и когда платить, и напомнит заранее. Кнопка «✅ Оплачено» сразу записывает расход.

<b>👥 Мастера</b> — добавьте мастеров и пришлите им ссылку-приглашение: они увидят свой график, смогут попросить выходной и будут получать напоминания о сменах.

<b>⚙️ Настройки</b> — рабочие дни, часы, сколько мастеров в смену, время напоминаний.

/cancel — отменить текущее действие."""

HELP_MASTER = """<b>Что умеет бот</b>

📅 <b>Мои смены</b> — ваши смены на 30 дней вперёд.
📆 <b>График салона</b> — кто работает на неделе.
🌴 <b>Хочу выходной</b> — укажите даты, администратор учтёт их при составлении графика.

Накануне смены бот пришлёт напоминание."""


def menu_for(role: str):
    return admin_menu() if role == ADMIN else staff_menu()


@router.message(CommandStart(deep_link=True))
async def start_with_invite(
    message: Message, command: CommandObject, state: FSMContext, db: Database, config: Config, role: str,
    bot: Bot,
) -> None:
    payload = command.args or ""
    if not payload.startswith("m"):
        await start(message, state, db, config, role)
        return
    await state.clear()
    master = await db.link_by_invite(payload[1:], message.from_user.id)
    if master is None:
        await message.answer("Ссылка-приглашение устарела. Попросите администратора прислать новую.")
        return
    role = ADMIN if role == ADMIN else MASTER
    await message.answer(
        f"Привет, {escape(master.name)}! 👋 Вы подключены к графику салона.\n\n{HELP_MASTER}",
        reply_markup=menu_for(role),
    )
    await notify_admins(
        bot, config, db, f"📱 {escape(master.name)} подключился(-ась) к боту.", exclude=message.from_user.id
    )


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, db: Database, config: Config, role: str) -> None:
    await state.clear()
    if role == GUEST and not await admin_ids(config, db):
        # First launch without ADMIN_IDS: whoever starts the bot first becomes the owner.
        await db.add_db_admin(message.from_user.id)
        role = ADMIN
        await message.answer("🔑 Вы первый пользователь — назначил вас владельцем салона.")
    if role == ADMIN:
        await message.answer(
            "Привет! Я помогу вести <b>график работы</b> мастеров и <b>график затрат</b> салона.\n\n"
            "Начните с раздела «👥 Мастера», затем откройте «📅 График работы» и нажмите «⚡ Составить».\n"
            "Подробнее — /help",
            reply_markup=admin_menu(),
        )
    elif role == MASTER:
        await message.answer(HELP_MASTER, reply_markup=staff_menu())
    else:
        await message.answer(
            "Это рабочий бот тату-салона, доступ есть только у сотрудников.\n"
            f"Ваш ID: <code>{message.from_user.id}</code>. Попросите у администратора ссылку-приглашение."
        )


@router.message(Command("help"))
async def help_command(message: Message, role: str) -> None:
    if role == ADMIN:
        await message.answer(HELP_ADMIN)
    elif role == MASTER:
        await message.answer(HELP_MASTER)
    else:
        await message.answer("Доступ есть только у сотрудников салона. Нажмите /start.")


@router.message(Command("id"))
async def my_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cancel_command(message: Message, state: FSMContext, role: str) -> None:
    await state.clear()
    markup = menu_for(role) if role != GUEST else None
    await message.answer("Отменено.", reply_markup=markup)


@router.callback_query(F.data == "cancel")
async def cancel_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message) and callback.message.text is not None:
        await callback.message.edit_text("Отменено.")
    await callback.answer("Отменено")
