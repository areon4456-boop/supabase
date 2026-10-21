from aiogram.fsm.state import State, StatesGroup


class AddExpense(StatesGroup):
    category = State()
    amount = State()


class AddPlanned(StatesGroup):
    title = State()
    category = State()
    amount = State()
    period = State()
    month_day = State()
    weekday = State()
    once_day = State()


class ShiftHours(StatesGroup):
    hours = State()


class DaysOffInput(StatesGroup):
    dates = State()


class MasterInput(StatesGroup):
    names = State()
    rename = State()


class SettingsInput(StatesGroup):
    hours = State()
    reminder_time = State()
