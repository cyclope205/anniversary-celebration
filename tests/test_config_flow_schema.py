"""Tests for the config_flow TTS entity-selector fix.

HA's EntitySelector (single, non-multiple) rejects an empty string with
"Entity is neither a valid entity ID nor a valid UUID" - a real bug that
blocked registering ANY person without a configured TTS engine, since
both CONF_ANNOUNCE_TTS_ENTITY and CONF_DEFAULT_ANNOUNCE_TTS_ENTITY default
to "" until the user picks one. The fix wraps the selector in
vol.Any("", selector.EntitySelector(...)) so the empty default validates.

Needs the real `homeassistant` package (see requirements_test.txt) - no
running Home Assistant instance, hass object, or event loop required:
EntitySelector's validation here is a pure value-format check.
"""
from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.helpers import selector


def _tts_selector():
  return selector.EntitySelector(selector.EntitySelectorConfig(domain="tts"))


def test_raw_tts_selector_rejects_empty_string():
  """Documents the bug: without the fix, this is what blocked saving."""
  with pytest.raises(vol.Invalid):
    _tts_selector()("")


def test_raw_tts_selector_accepts_a_real_looking_entity_id():
  assert _tts_selector()("tts.google_ai_tts") == "tts.google_ai_tts"


def _fixed_tts_field():
  # Same pattern used in config_flow.py for CONF_ANNOUNCE_TTS_ENTITY and
  # CONF_DEFAULT_ANNOUNCE_TTS_ENTITY.
  return vol.Any("", _tts_selector())


def test_fixed_tts_field_accepts_empty_string():
  """The actual regression test: nobody configuring a TTS engine must
  never block saving the form."""
  assert _fixed_tts_field()("") == ""


def test_fixed_tts_field_still_accepts_a_real_entity_id():
  assert _fixed_tts_field()("tts.google_ai_tts") == "tts.google_ai_tts"


def test_fixed_tts_field_still_rejects_garbage():
  """vol.Any("", ...) must not become a silent accept-anything: a typo'd
  or non-entity value should still be rejected."""
  with pytest.raises(vol.Invalid):
    _fixed_tts_field()("not-an-entity-id")
    
