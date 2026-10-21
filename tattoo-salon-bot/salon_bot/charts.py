"""PNG charts for Telegram: monthly shift grid and expense breakdown."""

from __future__ import annotations

import io
from datetime import date

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from .db import DayOff, Master, Shift  # noqa: E402
from .fmt import (  # noqa: E402
    MONTHS_SHORT,
    WEEKDAYS_SHORT,
    category_title,
    days_between,
    fmt_money,
    month_bounds,
    month_title,
)

# Light chart theme: one blue series hue, recessive chrome, text in ink tokens.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"
SERIES_SOFT = "#86b6ef"
EMPTY = "#f0efec"
CLOSED_HATCH = "#c3c2b7"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "text.color": INK,
        "axes.edgecolor": BASELINE,
        "axes.labelcolor": INK_SECONDARY,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
    }
)


def _to_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return buf.getvalue()


def _compact(rub: float) -> str:
    if rub >= 1_000_000:
        value, suffix = rub / 1_000_000, "М"
    elif rub >= 1000:
        value, suffix = rub / 1000, "К"
    else:
        return f"{rub:.0f}"
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",") + suffix


def schedule_png(
    year: int,
    month: int,
    masters: list[Master],
    shifts: list[Shift],
    days_off: list[DayOff],
    open_weekdays: set[int],
    today: date,
) -> bytes:
    """Masters as rows, days as columns; a filled cell is a shift."""
    days = days_between(*month_bounds(year, month))
    working = {(s.master_id, s.day) for s in shifts}
    off = {(o.master_id, o.day) for o in days_off}
    # Masters who were removed but still have shifts this month stay visible.
    known = {m.id for m in masters}
    extra = {s.master_id: s.master_name for s in shifts if s.master_id not in known}
    rows = [(m.id, m.name) for m in masters] + sorted(extra.items())

    n_days, n_rows = len(days), max(len(rows), 1)
    fig_w = 2.2 + n_days * 0.3
    fig_h = 1.3 + (n_rows + 1) * 0.36
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    gap = 0.12

    plt.rcParams["hatch.linewidth"] = 0.8
    for r, (master_id, _) in enumerate(rows):
        for c, day in enumerate(days):
            closed = day.weekday() not in open_weekdays
            cell = (c + gap / 2, r + gap / 2)
            if (master_id, day) in working:
                ax.add_patch(Rectangle(cell, 1 - gap, 1 - gap, facecolor=SERIES, lw=0))
            elif closed:
                ax.add_patch(Rectangle(cell, 1 - gap, 1 - gap, facecolor=SURFACE, edgecolor=CLOSED_HATCH,
                                       hatch="////", lw=0))
            else:
                ax.add_patch(Rectangle(cell, 1 - gap, 1 - gap, facecolor=EMPTY, lw=0))
            if (master_id, day) in off and (master_id, day) not in working:
                ax.text(c + 0.5, r + 0.52, "в", ha="center", va="center", color=INK_SECONDARY, fontsize=8)

    # Bottom row: how many masters work each day.
    total_row = n_rows
    for c, day in enumerate(days):
        count = sum((m_id, day) in working for m_id, _ in rows)
        closed = day.weekday() not in open_weekdays
        label = "" if closed and not count else ("!" if not count else str(count))
        weight = "bold" if label == "!" else "normal"
        ax.text(c + 0.5, total_row + 0.5, label, ha="center", va="center", fontsize=8, color=INK, weight=weight)

    for r, (master_id, name) in enumerate(rows):
        ax.text(-0.3, r + 0.5, name, ha="right", va="center", fontsize=9, color=INK)
        total = sum((master_id, d) in working for d in days)
        ax.text(n_days + 0.4, r + 0.5, str(total), ha="left", va="center", fontsize=9, color=INK, weight="bold")
    ax.text(-0.3, total_row + 0.5, "в смене", ha="right", va="center", fontsize=8, color=INK_SECONDARY)
    ax.text(n_days + 0.4, -0.9, "всего", ha="left", va="center", fontsize=7, color=INK_MUTED)

    for c, day in enumerate(days):
        is_today = day == today
        weekend = day.weekday() >= 5
        ax.text(
            c + 0.5, -0.9, str(day.day), ha="center", va="center", fontsize=8,
            color=INK if (weekend or is_today) else INK_SECONDARY, weight="bold" if (weekend or is_today) else "normal",
        )
        ax.text(c + 0.5, -0.35, WEEKDAYS_SHORT[day.weekday()][:2].lower(), ha="center", va="center",
                fontsize=6.5, color=INK_MUTED)
        if is_today:
            ax.plot([c + 0.15, c + 0.85], [-1.3, -1.3], color=INK, lw=1.5, solid_capstyle="round")

    ax.set_xlim(-0.1, n_days + 1.2)
    ax.set_ylim(total_row + 1.1, -1.5)
    ax.axis("off")
    ax.set_title(f"График работы · {month_title(year, month)}", loc="left", fontsize=12, color=INK,
                 weight="bold", pad=14)
    handles = [
        Patch(facecolor=SERIES, label="смена"),
        Patch(facecolor=SURFACE, edgecolor=CLOSED_HATCH, hatch="////", lw=0, label="салон закрыт"),
        Patch(facecolor=EMPTY, label="«в» — просил(а) выходной"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, 0), ncol=3, frameon=False, fontsize=8,
              handlelength=1.2, handleheight=1.2, labelcolor=INK_SECONDARY)
    if any(not sum((m_id, d) in working for m_id, _ in rows) and d.weekday() in open_weekdays for d in days):
        fig.text(0.01, 0.005, "! — в этот день никого нет", fontsize=7.5, color=INK_SECONDARY)
    return _to_png(fig)


def expenses_png(
    year: int,
    month: int,
    by_category: dict[str, int],
    history: list[tuple[int, int, int]],
    currency: str,
) -> bytes:
    """Top: the month by category. Bottom: monthly totals for the last months."""
    total = sum(by_category.values())
    items = sorted(by_category.items(), key=lambda kv: kv[1])
    n = max(len(items), 1)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7, 2.2 + n * 0.42 + 2.6), gridspec_kw={"height_ratios": [max(n, 2) * 0.42 + 0.6, 2.4]}
    )
    fig.patch.set_facecolor(SURFACE)

    ax1.set_facecolor(SURFACE)
    if items:
        labels = [category_title(code) for code, _ in items]
        values = [amount / 100 for _, amount in items]
        ax1.barh(labels, values, height=0.55, color=SERIES)
        peak = max(values)
        for y, value in enumerate(values):
            share = round(value * 10000 / total) if total else 0
            ax1.text(value + peak * 0.015, y, f"{fmt_money(round(value * 100), currency)}  {share}%",
                     va="center", ha="left", fontsize=8.5, color=INK)
        ax1.set_xlim(0, peak * 1.35)
    else:
        ax1.text(0.5, 0.5, "Расходов нет", ha="center", va="center", color=INK_MUTED, transform=ax1.transAxes)
    ax1.set_title(
        f"Расходы · {month_title(year, month)} — {fmt_money(total, currency)}",
        loc="left", fontsize=12, weight="bold", color=INK, pad=10,
    )
    ax1.xaxis.set_visible(False)
    ax1.tick_params(axis="y", length=0, labelsize=9, labelcolor=INK)
    for side in ("top", "right", "bottom"):
        ax1.spines[side].set_visible(False)

    ax2.set_facecolor(SURFACE)
    labels = [f"{MONTHS_SHORT[m - 1]}\n{y}" if m == 1 or i == 0 else MONTHS_SHORT[m - 1]
              for i, (y, m, _) in enumerate(history)]
    values = [t / 100 for _, _, t in history]
    colors = [SERIES if (y, m) == (year, month) else SERIES_SOFT for y, m, _ in history]
    xs = range(len(history))
    ax2.bar(xs, values, width=0.5, color=colors)
    peak = max(values) if values and max(values) > 0 else 1
    for x, value in zip(xs, values):
        if value:
            ax2.text(x, value + peak * 0.03, _compact(value), ha="center", va="bottom", fontsize=8, color=INK)
    ax2.set_xticks(list(xs), labels)
    ax2.set_ylim(0, peak * 1.2)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: _compact(v)))
    ax2.grid(axis="y", color=GRID, lw=0.8)
    ax2.set_axisbelow(True)
    ax2.tick_params(length=0)
    for side in ("top", "right", "left"):
        ax2.spines[side].set_visible(False)
    ax2.set_title("По месяцам", loc="left", fontsize=10, color=INK_SECONDARY, pad=8)

    fig.tight_layout(h_pad=2.0)
    return _to_png(fig)
