"""Pause OneDrive sync around long training/eval runs, then resume it.

The project lives inside a OneDrive-synced folder, so every checkpoint ``.save``
and every ``mlflow.db`` write triggers a sync. During training that means
constant file-lock contention on a 36 MB sqlite DB (slow runs, risk of DB
corruption). This module stops the OneDrive client while a run is in flight and
restarts it afterwards — including on ``Ctrl-C`` and on normal interpreter exit,
so sync is never left off by accident.

Usage (preferred — wrap the run)::

    from qube_rl.onedrive_guard import onedrive_paused
    with onedrive_paused():
        model.learn(...)

Standalone (manual / from a shell)::

    python -m qube_rl.onedrive_guard pause
    python -m qube_rl.onedrive_guard resume

It is a no-op on non-Windows platforms and when OneDrive is not installed, so it
is always safe to import and call.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

logger = logging.getLogger(__name__)

_PROCESS_NAME = "OneDrive.exe"
# Resume is idempotent; guard against double-restart from atexit + context exit.
_resumed_once = False


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _find_onedrive_exe() -> Path | None:
    """Return the OneDrive client path, or ``None`` if it is not installed."""
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft OneDrive" / _PROCESS_NAME,
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft OneDrive" / _PROCESS_NAME,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "OneDrive" / _PROCESS_NAME,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def pause() -> bool:
    """Stop the OneDrive client. Returns ``True`` if a stop was issued."""
    if not _is_windows():
        logger.debug("onedrive_guard: not Windows; pause is a no-op")
        return False
    # /F force, suppress the error when OneDrive is not currently running.
    result = subprocess.run(
        ["taskkill", "/IM", _PROCESS_NAME, "/F"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        logger.info("onedrive_guard: OneDrive sync PAUSED (process killed)")
        return True
    logger.info("onedrive_guard: OneDrive was not running (nothing to pause)")
    return False


def resume() -> bool:
    """Restart the OneDrive client in the background. Returns ``True`` on launch."""
    global _resumed_once
    if not _is_windows():
        return False
    exe = _find_onedrive_exe()
    if exe is None:
        logger.warning("onedrive_guard: OneDrive.exe not found; cannot resume sync")
        return False
    try:
        subprocess.Popen([str(exe), "/background"])
    except OSError as exc:
        logger.warning("onedrive_guard: failed to restart OneDrive: %s", exc)
        return False
    _resumed_once = True
    logger.info("onedrive_guard: OneDrive sync RESUMED (%s)", exe)
    return True


@contextmanager
def onedrive_paused(enabled: bool = True) -> Iterator[None]:
    """Pause OneDrive for the duration of the block, then guarantee a resume.

    Resume runs on normal exit, on exceptions, on ``Ctrl-C`` (SIGINT), and on
    interpreter shutdown (``atexit``) — whichever happens first — so sync is
    never silently left disabled.
    """
    if not enabled or not _is_windows():
        yield
        return

    global _resumed_once
    _resumed_once = False

    def _resume_once(*_args: object) -> None:
        global _resumed_once
        if not _resumed_once:
            resume()

    # Belt-and-suspenders: also resume if the process is killed or exits hard.
    atexit.register(_resume_once)
    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[sig] = signal.getsignal(sig)
        except (ValueError, OSError):  # not in main thread / unsupported
            previous_handlers[sig] = None

    pause()
    try:
        yield
    finally:
        _resume_once()
        atexit.unregister(_resume_once)
        for sig, handler in previous_handlers.items():
            if handler is not None:
                with suppress(ValueError, OSError):
                    signal.signal(sig, handler)


def _main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    action = argv[0].lower() if argv else "status"
    if action == "pause":
        pause()
    elif action == "resume":
        resume()
    else:
        print("usage: python -m qube_rl.onedrive_guard {pause|resume}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
