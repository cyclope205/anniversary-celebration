"""Date helpers for Anniversary Celebration."""
from __future__ import annotations

from datetime import date, datetime

# Deliberately no project-internal imports here (see tests/conftest.py):
# util.py is loaded directly from its file path in tests, without the
# custom_components package context, so a relative import (e.g.
# "from .const import ...") would always fail with ImportError. The field
# names below are kept as literals, in sync with the real constants of the
# same name in const.py (CONF_NOTIFY_TARGET, CONF_NOTIFY_TARGETS,
# CONF_NOTIFY_TIME, CONF_NOTIFY_TIME_2, CONF_NOTIFY_TIMES).
CONF_NOTIFY_TIME = "notify_time"
CONF_NOTIFY_TIME_2 = "notify_time_2"
CONF_NOTIFY_TIMES = "notify_times"
CONF_NOTIFY_TARGET = "notify_target"
CONF_NOTIFY_TARGETS = "notify_targets"
DEFAULT_NOTIFY_TIME = "09:00:00"


def parse_birth_date(value: str) -> date:
    """Parse an ISO (YYYY-MM-DD) birth date string."""
    return date.fromisoformat(value)


_FLEXIBLE_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d")


def parse_flexible_date(value: str) -> date:
    """Parse a birth date typed by hand in the config flow's text field.

    The native HA date-picker calendar requires clicking back one month at
    a time to reach an old date (e.g. a 1949 birth date), which is
    impractical. The config flow therefore accepts the date as typed
    text, in ISO (YYYY-MM-DD) or common day/month/year notations, parsed
    here. Raises ValueError if nothing matches, so the caller can show a
    form error without crashing.
    """
    value = (value or "").strip()
    for fmt in _FLEXIBLE_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {value!r}")


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


def _parse_hhmm(time_str: str | None) -> tuple[int, int]:
    """Parse a 'HH:MM' or 'HH:MM:SS' string into (hour, minute), defaulting to 00:00."""
    value = time_str or "00:00:00"
    try:
        hh, mm, *_ = (int(x) for x in value.split(":"))
        return hh, mm
    except ValueError:
        return 0, 0


def normalize_notify_times(person: dict) -> list[str]:
    """Return the list of configured notification times for a person.

    Reads the current CONF_NOTIFY_TIMES list field when present and
    non-empty. Otherwise falls back to the legacy singular
    CONF_NOTIFY_TIME / CONF_NOTIFY_TIME_2 fields, so people configured
    before this was a list keep working without being re-edited. Always
    returns at least one time (DEFAULT_NOTIFY_TIME as a last resort).
    """
    times = person.get(CONF_NOTIFY_TIMES)
    if isinstance(times, list) and times:
        return [t for t in times if t]

    legacy: list[str] = []
    first = person.get(CONF_NOTIFY_TIME)
    if first:
        legacy.append(first)
    second = person.get(CONF_NOTIFY_TIME_2)
    if second:
        legacy.append(second)

    return legacy or [DEFAULT_NOTIFY_TIME]


def normalize_notify_targets(person: dict) -> list[str]:
    """Return the list of configured notify.* targets for a person.

    Reads the current CONF_NOTIFY_TARGETS list field when present and
    non-empty. Otherwise falls back to the legacy singular
    CONF_NOTIFY_TARGET field, so people configured before this was a
    multi-select keep notifying the same device without being re-edited.
    Returns an empty list when no target is configured at all.
    """
    targets = person.get(CONF_NOTIFY_TARGETS)
    if isinstance(targets, list) and targets:
        return [t for t in targets if t]

    legacy = person.get(CONF_NOTIFY_TARGET)
    return [legacy] if legacy else []


def should_notify(
    birth: date,
    today: date,
    now_hour: int,
    now_minute: int,
    notify_time: str | None,
    last_notified_iso: str | None,
) -> bool:
    """Decide, for this minute's recheck, whether to send the notification.

    Kept for backward compatibility with any external caller relying on
    the single-time signature. New code should use due_slots() instead,
    which supports more than one notification time per person.
    """
    if days_until(birth, today) != 0:
        return False
    if last_notified_iso == today.isoformat():
        return False
    hh, mm = _parse_hhmm(notify_time)
    return (now_hour, now_minute) >= (hh, mm)


def due_slots(
    birth: date,
    today: date,
    now_hour: int,
    now_minute: int,
    notify_times: list[str],
    sent_slots_today: dict[str, str],
) -> list[int]:
    """Return the indexes of notify_times that are due and not yet sent today.

    A slot (one configured notification time) is due when: today is the
    anniversary, the slot's time has been reached, and
    sent_slots_today doesn't already record today's ISO date for that
    slot index (as a string key, since persisted JSON keys are always
    strings). Returning indexes rather than a single bool lets the
    caller send each configured time independently and mark only the
    slots that actually fired, so a restart that misses one slot doesn't
    block the others, and a slot already sent today is never repeated.
    """
    if days_until(birth, today) != 0:
        return []

    today_iso = today.isoformat()
    due: list[int] = []
    for index, time_str in enumerate(notify_times):
        hh, mm = _parse_hhmm(time_str)
        if (now_hour, now_minute) < (hh, mm):
            continue
        if sent_slots_today.get(str(index)) == today_iso:
            continue
        due.append(index)
    return due
