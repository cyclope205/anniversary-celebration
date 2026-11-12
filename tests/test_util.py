"""Unit tests for the pure date-math helpers in util.py.

These functions are the reliability-critical core of the integration:
they decide, every minute, whether "today" is someone's anniversary.
A bug here would mean a missed or duplicated notification.
"""
from __future__ import annotations

from datetime import date

import pytest


def test_parse_birth_date(util):
    assert util.parse_birth_date("1990-05-17") == date(1990, 5, 17)


def test_parse_flexible_date_iso(util):
    assert util.parse_flexible_date("1949-11-12") == date(1949, 11, 12)


def test_parse_flexible_date_slash_dmy(util):
    # The exact case that motivated this parser: typing an old date
    # (e.g. 1949) instead of clicking "previous month" dozens of times.
    assert util.parse_flexible_date("12/11/1949") == date(1949, 11, 12)


def test_parse_flexible_date_dash_dmy(util):
    assert util.parse_flexible_date("12-11-1949") == date(1949, 11, 12)


def test_parse_flexible_date_dot_dmy(util):
    assert util.parse_flexible_date("12.11.1949") == date(1949, 11, 12)


def test_parse_flexible_date_slash_ymd(util):
    assert util.parse_flexible_date("1949/11/12") == date(1949, 11, 12)


def test_parse_flexible_date_strips_whitespace(util):
    assert util.parse_flexible_date("  1949-11-12  ") == date(1949, 11, 12)


def test_parse_flexible_date_rejects_garbage(util):
    with pytest.raises(ValueError):
        util.parse_flexible_date("not a date")


def test_parse_flexible_date_rejects_empty(util):
    with pytest.raises(ValueError):
        util.parse_flexible_date("")


def test_next_anniversary_later_this_year(util):
    birth = date(1990, 12, 25)
    today = date(2026, 1, 1)
    assert util.next_anniversary(birth, today) == date(2026, 12, 25)


def test_next_anniversary_already_passed_rolls_to_next_year(util):
    birth = date(1990, 3, 1)
    today = date(2026, 11, 12)
    assert util.next_anniversary(birth, today) == date(2027, 3, 1)


def test_next_anniversary_today_is_the_day(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.next_anniversary(birth, today) == today


def test_next_anniversary_feb29_on_non_leap_year(util):
    birth = date(2000, 2, 29)
    today = date(2026, 1, 1)  # 2026 is not a leap year
    assert util.next_anniversary(birth, today) == date(2026, 3, 1)


def test_next_anniversary_feb29_on_leap_year(util):
    birth = date(2000, 2, 29)
    today = date(2027, 6, 1)
    # 2028 is a leap year: Feb 29 exists again
    assert util.next_anniversary(birth, today) == date(2028, 2, 29)


def test_days_until_is_zero_today(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.days_until(birth, today) == 0


def test_days_until_counts_forward(util):
    birth = date(1980, 11, 22)
    today = date(2026, 11, 12)
    assert util.days_until(birth, today) == 10


def test_days_until_never_negative_across_year_boundary(util):
    birth = date(1980, 1, 5)
    today = date(2026, 12, 30)
    assert util.days_until(birth, today) == 6


def test_current_age_before_birthday_this_year(util):
    birth = date(1990, 12, 25)
    today = date(2026, 11, 12)
    assert util.current_age(birth, today) == 35


def test_current_age_on_birthday(util):
    birth = date(1990, 11, 12)
    today = date(2026, 11, 12)
    assert util.current_age(birth, today) == 36


def test_current_age_after_birthday_this_year(util):
    birth = date(1990, 1, 1)
    today = date(2026, 11, 12)
    assert util.current_age(birth, today) == 36


def test_age_at_next_anniversary_matches_current_plus_one_before_birthday(util):
    birth = date(1990, 12, 25)
    today = date(2026, 11, 12)
    assert util.age_at_next_anniversary(birth, today) == 36
    assert util.current_age(birth, today) == 35


def test_age_at_next_anniversary_on_the_day_equals_current_age(util):
    # The HA "Anniversaries" convention this integration mirrors: on the
    # actual day, years_at_anniversary == the age just reached.
    birth = date(1960, 11, 12)
    today = date(2026, 11, 12)
    assert util.age_at_next_anniversary(birth, today) == util.current_age(birth, today)
