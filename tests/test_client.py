"""Tests for ESP32 HTTP client."""

from __future__ import annotations

from typing import Any

from qube_ui.client import QubeState


class TestQubeState:
    """Tests for QubeState dataclass."""

    def test_from_json_full(self, sample_state_json: dict[str, Any]) -> None:
        """Test creating QubeState from a full JSON payload."""
        state = QubeState.from_json(sample_state_json)
        assert state.mode == 2
        assert state.count == 2048
        assert state.enc_a == 1
        assert state.enc_b == 0
        assert state.encoder_dir == 1
        assert state.counts_per_rev == 2048.0
        assert state.raw_position_deg == 45.2
        assert state.position_deg == 45.2
        assert state.offset_deg == 0.0
        assert state.setpoint_deg == 45.0
        assert state.error_deg == 0.2
        assert state.pwm == 12
        assert state.ina_ok is True
        assert state.v_bus == 11.8
        assert state.v_shunt_mv == 45.0
        assert state.i_ma == 380.5
        assert state.p_mw == 4490.0
        assert state.timestamp > 0  # timestamp is set to current time

    def test_from_json_empty(self) -> None:
        """Test creating QubeState from empty dict."""
        state = QubeState.from_json({})
        assert state.mode == 0
        assert state.count == 0
        assert state.extra == {}

    def test_from_json_extra_fields(self) -> None:
        """Test that unknown fields go to extra dict."""
        data = {"mode": 1, "unknown_field": "test_value", "position_deg": 10.0}
        state = QubeState.from_json(data)
        assert state.mode == 1
        assert state.position_deg == 10.0
        assert state.extra == {"unknown_field": "test_value"}

    def test_defaults(self) -> None:
        """Test default values of QubeState."""
        state = QubeState()
        assert state.mode == 0
        assert state.counts_per_rev == 2048.0
        assert state.ina_ok is False
        assert state.extra == {}


class TestESP32Client:
    """Tests for ESP32Client."""

    def test_default_ip(self) -> None:
        """Test default IP address."""
        from qube_ui.client import ESP32Client

        client = ESP32Client()
        assert client.ip == "192.168.4.1"

    def test_custom_ip(self) -> None:
        """Test custom IP address."""
        from qube_ui.client import ESP32Client

        client = ESP32Client(ip="10.0.0.1")
        assert client.ip == "10.0.0.1"
