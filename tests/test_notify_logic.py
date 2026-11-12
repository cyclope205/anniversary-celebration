"""Tests for should_notify(): the anti-duplicate / anti-miss decision made
every minute by the integration's recheck loop.

This is the function the "100% reliability" guarantee rests on: it must
return True exactly once per person per anniversary day, regardless of
how many times per day it is called, and regardless of HA restarts in
between calls (simulated here by simply calling it again with the same
persisted "last_notified_iso" value).
"""
from __future__ import annotations

from datetime import date


def test_not_the_day_never_notifies(util):
    birth = date(1980, 12, 25)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 23, 59, None, None) is False


def test_the_day_no_time_configured_notifies_any_time(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 0, 0, None, None) is True


def test_the_day_before_configured_time_waits(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 8, 29, "08:30:00", None) is False


def test_the_day_at_configured_time_notifies(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 8, 30, "08:30:00", None) is True


def test_the_day_after_configured_time_notifies(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 23, 0, "08:30:00", None) is True


def test_already_notified_today_never_fires_again(util):
    # Simulates every later per-minute recheck on the same day, and a
    # recheck right after a HA restart that happened later that same day.
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 12, 0, "08:30:00", "2026-11-12") is False


def test_notified_on_a_previous_year_does_not_block_this_year(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 12, 0, "08:30:00", "2025-11-12") is True


def test_malformed_notify_time_falls_back_to_midnight(util):
    birth = date(1980, 11, 12)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 0, 1, "not-a-time", None) is True


def test_restart_months_before_anniversary_does_not_prematurely_notify(util):
    # The core "8 months away" scenario from the original request: a
    # restart long before the anniversary must not cause anything to fire.
    birth = date(1980, 7, 4)
    today = date(2026, 11, 12)
    assert util.should_notify(birth, today, 12, 0, None, None) is False
