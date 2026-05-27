"""Thread-safe circular buffer for real-time signal data."""

from __future__ import annotations

import threading
from collections import deque
from typing import Protocol


class TimeSeriesSample(Protocol):
    """Protocol for samples that can be stored in a SignalBuffer."""

    timestamp: float


class SignalBuffer:
    """Thread-safe circular buffer for storing time-series samples.

    Args:
        maxlen: Maximum number of samples to store.
    """

    def __init__(self, maxlen: int = 3000) -> None:
        self._maxlen = maxlen
        self._lock = threading.Lock()
        self._data: deque[TimeSeriesSample] = deque(maxlen=maxlen)
        self._t0: float | None = None

    @property
    def maxlen(self) -> int:
        """Maximum capacity of the buffer."""
        return self._maxlen

    @property
    def size(self) -> int:
        """Current number of samples in the buffer."""
        with self._lock:
            return len(self._data)

    def push(self, sample: TimeSeriesSample) -> None:
        """Add a sample to the buffer (thread-safe)."""
        with self._lock:
            if self._t0 is None:
                self._t0 = sample.timestamp
            self._data.append(sample)

    def get_all(self) -> list[TimeSeriesSample]:
        """Get all samples as a list (thread-safe)."""
        with self._lock:
            return list(self._data)

    def get_window(self, window_seconds: float) -> list[TimeSeriesSample]:
        """Get samples within the last window_seconds (thread-safe)."""
        with self._lock:
            if not self._data or self._t0 is None:
                return []
            t_max = self._data[-1].timestamp
            t_min = t_max - window_seconds
            return [s for s in self._data if s.timestamp >= t_min]

    def clear(self) -> None:
        """Clear all data (thread-safe)."""
        with self._lock:
            self._data.clear()
            self._t0 = None

    def elapsed(self) -> float:
        """Get elapsed time since first sample (thread-safe)."""
        with self._lock:
            if not self._data or self._t0 is None:
                return 0.0
            return self._data[-1].timestamp - self._t0
