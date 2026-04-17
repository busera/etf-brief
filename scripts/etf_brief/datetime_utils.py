"""Timezone-safe datetime helpers for the etf-brief skill.

Always use :func:`now_berlin` / :func:`today_berlin` instead of
``datetime.now()`` or ``date.today()`` to avoid bugs where UTC midnight
does not coincide with Berlin midnight (common when cron fires near
midnight).

All market data in this project is timestamped in Europe/Berlin.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

BERLIN_TZ: ZoneInfo = ZoneInfo("Europe/Berlin")


def now_berlin() -> datetime:
    """Return the current timezone-aware datetime in Europe/Berlin.

    Returns:
        A :class:`datetime.datetime` with ``tzinfo=BERLIN_TZ``.
    """
    return datetime.now(tz=BERLIN_TZ)


def today_berlin() -> date:
    """Return the current Berlin-local calendar date.

    Returns:
        A :class:`datetime.date` matching the Europe/Berlin wall clock.
    """
    return now_berlin().date()
