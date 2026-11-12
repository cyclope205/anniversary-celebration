"""Date helpers for Anniversary Celebration."""
from __future__ import annotations

from datetime import date


def parse_birth_date(value: str) -> date:
    """Parse an ISO (YYYY-MM-DD) birth date string."""
    return date.fromisoformat(value)


def next_anniversary(birth: date, today: date) -> date:
    """Return the next occurrence (today or future) of the birth month/day."""
    try:
        candidate = birth.replace(year=today.year)
    except ValueError:
        # Feb 29 on a non-leap year -> celebrate Mar 1
        candidate = date(today.year, 3, 1)
    if candidate < today:
        try:
            candidate = birth.replace(year=today.year + 1)
        except ValueError:
            candidate = date(today.year + 1, 3, 1)
    return candidate


def days_until(birth: date, today: date) -> int:
    """Days remaining until the next anniversary (0 = today)."""
    return (next_anniversary(birth, today) - today).days


def current_age(birth: date, today: date) -> int:
    """Age already reached as of today."""
    age = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        age -= 1
    return age


def age_at_next_anniversary(birth: date, today: date) -> int:
    """Age the person turns / would turn on the next anniversary."""
    nxt = next_anniversary(birth, today)
    return nxt.year - birth.year


def should_notify(
    birth: date,
    today: date,
    now_hour: int,
    now_minute: int,
    notify_time: str | None,
    last_notified_iso: str | None,
) -> bool:
    """Decide, for this minute's recheck, whether to send the notification.

    True only when: today is the anniversary, the configured notification
    time has been reached, and no notification has already been recorded
    for today (last_notified_iso == today's ISO date would mean "already
    sent" and must return False). This is the single source of truth the
    per-minute loop relies on, so a HA restart months before an upcoming
    anniversary can never cause a miss (re-evaluated from scratch every
    minute), and so a restart on the day itself can never cause a
    duplicate (the persisted last_notified_iso survives the restart).
    """
    if days_until(birth, today) != 0:
        return False
    if last_notified_iso == today.isoformat():
        return False
    time_str = notify_time or "00:00:00"
    try:
        hh, mm, *_ = (int(x) for x in time_str.split(":"))
    except ValueError:
        hh, mm = 0, 0
    return (now_hour, now_minute) >= (hh, mm)
