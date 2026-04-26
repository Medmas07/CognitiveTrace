"""Active application tracking (OS-level)."""

from __future__ import annotations

import ctypes
import logging
import platform
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional, Set

try:
    import psutil
except ImportError:  # handled by startup validation
    psutil = None  # type: ignore[assignment]

from shared.time_utils import now_ns

LOGGER = logging.getLogger(__name__)

# Minimum seconds between consecutive active_app_change emissions.
# Prevents high-frequency spam when window titles change rapidly (e.g. browser tabs).
_MIN_CHANGE_INTERVAL_SEC: float = 1.0


def _parse_app_context(process_name: str, window_title: str) -> str:
    """Return the most useful context string for an active-app event.

    VSCode  – title format "● filename.ext - folder - Visual Studio Code"
              → returns the filename (strips unsaved marker, folder, app suffix).
    Others  – returns the full window title unchanged.
    """
    title = (window_title or "").strip()
    if not title:
        return ""
    proc = process_name.lower()
    # code.exe is VSCode; guard also covers titles that explicitly say "Visual Studio Code"
    if proc == "code.exe" or ("code" in proc and "visual studio code" in title.lower()):
        parts = [p.strip() for p in title.split(" - ")]
        # First segment is the open file; strip the unsaved-file marker (●)
        first = parts[0].lstrip("●").strip()
        if first and first.lower() not in {"visual studio code"}:
            return first
        return ""
    return title


@dataclass(frozen=True)
class AppSnapshot:
    timestamp_ns: int
    process_name: str
    window_title: str
    pid: int | None
    is_browser: bool

    @property
    def app_name(self) -> str:
        return self.process_name or "unknown"

    @property
    def context(self) -> str:
        """Parsed, human-useful context extracted from the window title."""
        return _parse_app_context(self.process_name, self.window_title)


class AppTracker:
    """Polls active OS window and emits change notifications."""

    def __init__(
        self,
        poll_interval_sec: float,
        browser_processes: Set[str],
        on_change: Callable[[AppSnapshot], None],
    ) -> None:
        self._poll_interval_sec = poll_interval_sec
        self._browser_processes = {name.lower() for name in browser_processes}
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_snapshot: Optional[AppSnapshot] = None

        self._is_windows = platform.system().lower() == "windows"
        if not self._is_windows:
            LOGGER.warning("AppTracker currently supports Windows best; fallback will be 'unknown'.")

    @property
    def current_snapshot(self) -> Optional[AppSnapshot]:
        return self._last_snapshot

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="app-tracker", daemon=True)
        self._thread.start()

    def stop(self, timeout_sec: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout_sec)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            snapshot = self._capture_snapshot()
            if self._has_changed(snapshot):
                self._last_snapshot = snapshot
                try:
                    self._on_change(snapshot)
                except Exception as exc:  # pragma: no cover - callback safety
                    LOGGER.exception("AppTracker callback failed: %s", exc)

            time.sleep(self._poll_interval_sec)

    def _has_changed(self, snapshot: AppSnapshot) -> bool:
        previous = self._last_snapshot
        if previous is None:
            return True
        # Emit only when the active *process* (app) changes.
        # Ignoring window_title prevents high-frequency spam from browser tab
        # title updates (e.g. YouTube progress, live dashboards).
        if previous.process_name == snapshot.process_name:
            return False
        # Debounce: drop events that arrive faster than the minimum interval
        # even if the process name did change (rapid alt-tab sequences).
        elapsed_sec = (snapshot.timestamp_ns - previous.timestamp_ns) / 1_000_000_000
        if elapsed_sec < _MIN_CHANGE_INTERVAL_SEC:
            return False
        return True

    def _capture_snapshot(self) -> AppSnapshot:
        if self._is_windows:
            return self._capture_windows()
        return AppSnapshot(
            timestamp_ns=now_ns(),
            process_name="unknown",
            window_title="unsupported-platform",
            pid=None,
            is_browser=False,
        )

    def _capture_windows(self) -> AppSnapshot:
        if psutil is None:
            raise RuntimeError(
                "AppTracker requires `psutil` for foreground process detection. "
                "Install with `pip install psutil`."
            )

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return AppSnapshot(
                timestamp_ns=now_ns(),
                process_name="unknown",
                window_title="",
                pid=None,
                is_browser=False,
            )

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        title_buffer = ctypes.create_unicode_buffer(1024)
        user32.GetWindowTextW(hwnd, title_buffer, 1024)
        window_title = title_buffer.value

        process_name = "unknown"
        proc_pid = int(pid.value) if pid.value else None
        if proc_pid:
            try:
                process_name = psutil.Process(proc_pid).name().lower()
            except Exception:
                process_name = "unknown"

        return AppSnapshot(
            timestamp_ns=now_ns(),
            process_name=process_name,
            window_title=window_title,
            pid=proc_pid,
            is_browser=process_name in self._browser_processes,
        )
