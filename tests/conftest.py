"""Shared fixtures and configuration for tests."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def sample_state_json() -> dict[str, Any]:
    """Return a sample JSON response from the ESP32 /state endpoint."""
    return {
        "mode": 2,
        "count": 2048,
        "enc_a": 1,
        "enc_b": 0,
        "encoder_dir": 1,
        "counts_per_rev": 2048.0,
        "raw_position_deg": 45.2,
        "position_deg": 45.2,
        "offset_deg": 0.0,
        "setpoint_deg": 45.0,
        "error_deg": 0.2,
        "pwm": 12,
        "ina_ok": True,
        "v_bus": 11.8,
        "v_shunt_mv": 45.0,
        "i_ma": 380.5,
        "p_mw": 4490.0,
        "t": 1234567,
    }
