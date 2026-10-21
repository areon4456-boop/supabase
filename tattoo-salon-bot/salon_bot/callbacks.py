"""Inline button payloads. Values must not contain ":" (the CallbackData separator)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class WeekCb(CallbackData, prefix="wk"):
    start: str  # ISO date of the Monday


class MonthCb(CallbackData, prefix="mo"):
    action: str  # img | xlsx | gen | genok
    ym: str


class DayCb(CallbackData, prefix="dy"):
    action: str  # open | toggle | hours
    day: str
    master_id: int = 0


class OffCb(CallbackData, prefix="off"):
    action: str  # list | add | del
    master_id: int = 0
    day: str = ""


class MasterCb(CallbackData, prefix="ms"):
    action: str  # list | add | open | rename | invite | unlink | off | delete | delok
    id: int = 0


class CatCb(CallbackData, prefix="cat"):
    flow: str  # exp | plan
    code: str


class ExpCb(CallbackData, prefix="ex"):
    action: str  # add | recent | del | delr (from the recent list)
    id: int = 0


class ReportCb(CallbackData, prefix="rp"):
    action: str  # show | chart | xlsx
    ym: str


class PayCb(CallbackData, prefix="py"):
    action: str  # month | pay | new | list | del
    ym: str = ""
    id: int = 0
    due: str = ""


class PeriodCb(CallbackData, prefix="pr"):
    period: str  # monthly | weekly | once


class WeekdayCb(CallbackData, prefix="wd"):
    day: int


class SetCb(CallbackData, prefix="st"):
    action: str  # show | days | day | hours | perday | perdayset | streak | streakset | remtime | remtoggle
    value: int = 0
