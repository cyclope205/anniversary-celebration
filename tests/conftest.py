"""Shared test fixtures.

util.py has zero Home Assistant dependencies (pure date math), so it is
loaded directly from its file path rather than through the
custom_components package import, which would otherwise require a full
Home Assistant install just to execute __init__.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_UTIL_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "anniversary_celebration"
    / "util.py"
)


@pytest.fixture(scope="session")
def util():
    spec = importlib.util.spec_from_file_location("ac_util", _UTIL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ac_util"] = module
    spec.loader.exec_module(module)
    return module
