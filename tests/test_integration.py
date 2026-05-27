"""Integration tests for QUBE UI components."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from qube_ui.buffer import SignalBuffer
from qube_ui.client import ESP32Client, QubeState


class TestQubeStateTimestamp:
    """Tests for QubeState timestamp handling."""

    def test_timestamp_set_on_creation(self) -> None:
        """Test that timestamp is set when creating QubeState."""
        before = time.time()
        state = QubeState.from_json({"mode": 1})
        after = time.time()

        assert before <= state.timestamp <= after

    def test_timestamp_custom(self) -> None:
        """Test that custom timestamp can be provided."""
        custom_ts = 1234567890.0
        state = QubeState.from_json({}, ts=custom_ts)

        assert state.timestamp == custom_ts


class TestSignalBufferIntegration:
    """Integration tests for SignalBuffer."""

    def test_push_and_get_all(self) -> None:
        """Test pushing states and getting all samples."""
        buffer = SignalBuffer(maxlen=100)

        # Create mock states
        for i in range(10):
            state = QubeState(
                timestamp=time.time() + i * 0.1,
                position_deg=float(i),
                setpoint_deg=10.0,
                error_deg=10.0 - i,
                pwm=i * 10,
                i_ma=float(i * 100),
                v_bus=12.0,
                p_mw=float(i * 1000),
            )
            buffer.push(state)

        # Get all samples
        samples = buffer.get_all()

        assert len(samples) == 10
        assert samples[0].position_deg == 0.0
        assert samples[-1].position_deg == 9.0

    def test_thread_safety(self) -> None:
        """Test that buffer is thread-safe."""
        buffer = SignalBuffer(maxlen=1000)
        errors = []

        def writer() -> None:
            try:
                for i in range(100):
                    state = QubeState(
                        timestamp=time.time(),
                        position_deg=float(i),
                    )
                    buffer.push(state)
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(50):
                    buffer.get_all()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Run writer and reader in parallel
        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)

        writer_thread.start()
        reader_thread.start()

        writer_thread.join()
        reader_thread.join()

        assert len(errors) == 0
        assert buffer.size > 0


class TestESP32ClientMocked:
    """Tests for ESP32Client with mocked HTTP responses."""

    def test_client_initialization(self) -> None:
        """Test client initialization with custom parameters."""
        client = ESP32Client(
            ip="10.0.0.1",
            port=8080,
            poll_ms=50,
            on_update=lambda _: None,
            on_error=lambda _: None,
        )

        assert client.ip == "10.0.0.1"
        assert client.port == 8080
        assert client.poll_ms == 50

    def test_send_cmd_builds_correct_url(self) -> None:
        """Test that send_cmd builds the correct URL."""
        client = ESP32Client(ip="192.168.1.100")

        with patch("qube_ui.client.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            client.send_cmd(m=2, s=45.0)

            # Verify the URL was called with correct parameters
            call_args = mock_urlopen.call_args
            url = call_args[0][0]
            assert "m=2" in url
            assert "s=45.0" in url

    def test_stop_motor_sends_correct_command(self) -> None:
        """Test that stop_motor sends x=1 command."""
        client = ESP32Client()

        with patch.object(client, "send_cmd") as mock_send:
            mock_send.return_value = True
            client.stop_motor()

            mock_send.assert_called_once_with(x=1)

    def test_set_pid_sends_correct_parameters(self) -> None:
        """Test that set_pid sends correct PID parameters."""
        client = ESP32Client()

        with patch.object(client, "send_cmd") as mock_send:
            mock_send.return_value = True
            client.set_pid(0.75, 0.15, 0.06)

            mock_send.assert_called_once_with(kp=0.75, ki=0.15, kd=0.06)
