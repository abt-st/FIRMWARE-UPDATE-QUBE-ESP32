"""Tests for SignalBuffer."""

from __future__ import annotations

from qube_ui.buffer import SignalBuffer


class TestSignalBuffer:
    """Tests for SignalBuffer (thread-safe circular buffer)."""

    def test_init_empty(self) -> None:
        """Test initial state is empty."""
        buf = SignalBuffer(maxlen=100)
        assert buf.size == 0
        assert buf.maxlen == 100
        assert buf.get_all() == []
        assert buf.elapsed() == 0.0

    def test_push_and_size(self) -> None:
        """Test pushing samples increases size."""
        buf = SignalBuffer(maxlen=10)
        buf.push(type("Sample", (), {"timestamp": 1.0})())
        assert buf.size == 1
        buf.push(type("Sample", (), {"timestamp": 2.0})())
        assert buf.size == 2

    def test_get_all_returns_all(self) -> None:
        """Test get_all returns all samples."""
        buf = SignalBuffer(maxlen=100)
        for i in range(5):
            buf.push(type("Sample", (), {"timestamp": float(i)})())
        samples = buf.get_all()
        assert len(samples) == 5
        assert [s.timestamp for s in samples] == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_maxlen_enforced(self) -> None:
        """Test that maxlen limits the buffer size."""
        buf = SignalBuffer(maxlen=3)
        for i in range(5):
            buf.push(type("Sample", (), {"timestamp": float(i)})())
        assert buf.size == 3
        samples = buf.get_all()
        assert [s.timestamp for s in samples] == [2.0, 3.0, 4.0]

    def test_clear(self) -> None:
        """Test clear empties the buffer."""
        buf = SignalBuffer(maxlen=100)
        buf.push(type("Sample", (), {"timestamp": 1.0})())
        buf.clear()
        assert buf.size == 0
        assert buf.get_all() == []

    def test_elapsed(self) -> None:
        """Test elapsed time calculation."""
        buf = SignalBuffer(maxlen=100)
        assert buf.elapsed() == 0.0
        buf.push(type("Sample", (), {"timestamp": 10.0})())
        assert buf.elapsed() == 0.0
        buf.push(type("Sample", (), {"timestamp": 15.0})())
        assert buf.elapsed() == 5.0

    def test_get_window(self) -> None:
        """Test get_window returns samples within time window."""
        buf = SignalBuffer(maxlen=100)
        for i in range(10):
            buf.push(type("Sample", (), {"timestamp": float(i)})())
        window = buf.get_window(window_seconds=3.5)
        assert len(window) == 4
        assert [s.timestamp for s in window] == [6.0, 7.0, 8.0, 9.0]

    def test_get_window_empty(self) -> None:
        """Test get_window returns empty list when buffer is empty."""
        buf = SignalBuffer(maxlen=100)
        assert buf.get_window(5.0) == []
