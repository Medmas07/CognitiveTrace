from __future__ import annotations

import ctypes
import logging
import time
from typing import Optional

import psutil

from filters import classify_event_type, should_drop_event
from influx_client import InfluxBatchClient, now_ns
from models import Event


class BehaviorCollector:
    """Collects app-level focus/switch/idle events with duration only."""

    def __init__(
        self,
        influx_client: InfluxBatchClient,
        user_id: str = "u1",
        poll_interval: float = 0.5,
        emit_interval: float = 3.0,
        merge_flush_threshold: float = 6.0,
    ) -> None:
        self.influx_client = influx_client
        self.user_id = user_id
        self.poll_interval = poll_interval
        self.emit_interval = emit_interval
        self.merge_flush_threshold = merge_flush_threshold

        self._running = False
        self._current_app = "unknown"
        self._last_event_monotonic = 0.0
        self._pending_event: Optional[Event] = None

        self._user32 = ctypes.windll.user32

    def request_stop(self) -> None:
        self._running = False

    def run_forever(self) -> None:
        self._running = True

        self._current_app = self._get_active_app_name()
        self._last_event_monotonic = time.monotonic()

        logging.info("System collector started")

        try:
            while self._running:
                self._poll_tick()
                time.sleep(self.poll_interval)
        finally:
            self._shutdown()

    def _poll_tick(self) -> None:
        now_monotonic = time.monotonic()
        active_app = self._get_active_app_name()
        app_changed = active_app != self._current_app
        elapsed = max(0.0, now_monotonic - self._last_event_monotonic)

        if app_changed:
            self._handle_event_window(
                app_name=self._current_app,
                duration=elapsed,
                app_changed=True,
            )
            self._current_app = active_app
            self._last_event_monotonic = now_monotonic
            return

        if elapsed >= self.emit_interval:
            self._handle_event_window(
                app_name=self._current_app,
                duration=elapsed,
                app_changed=False,
            )
            self._last_event_monotonic = now_monotonic

    def _handle_event_window(self, app_name: str, duration: float, app_changed: bool) -> None:
        # Behavioral filtering intentionally uses duration, not process name.
        # Name-based allow/deny lists are brittle and leak system-specific bias.
        if should_drop_event(duration):
            return

        event_type = classify_event_type(duration, app_changed)
        event = Event(
            timestamp=now_ns(),
            app_name=app_name or "unknown",
            event_type=event_type,
            duration=duration,
            user_id=self.user_id,
            source_type="app",
        )

        if event.event_type == "switch":
            self._flush_pending_event(force=True)
            # One user event must map to one Influx point.
            # Creating multiple points for a single transition breaks graph edges.
            self.influx_client.enqueue_line(event.to_line_protocol())
            return

        # Focus/idle intervals from the same app are merged before write.
        # Writing each tiny slice separately would fragment sessions.
        if (
            self._pending_event
            and self._pending_event.app_name == event.app_name
            and self._pending_event.event_type in {"focus", "idle"}
        ):
            self._pending_event.duration += event.duration
            self._pending_event.timestamp = event.timestamp
            self._pending_event.event_type = classify_event_type(
                self._pending_event.duration,
                app_changed=False,
            )
        else:
            self._flush_pending_event(force=True)
            self._pending_event = event

        self._flush_pending_event(force=False)

    def _flush_pending_event(self, force: bool) -> None:
        if self._pending_event is None:
            return
        if not force and self._pending_event.duration < self.merge_flush_threshold:
            return

        # Cumulative duration written repeatedly is incorrect because each point
        # would re-count older time. We write only finalized merged intervals.
        self.influx_client.enqueue_line(self._pending_event.to_line_protocol())
        self._pending_event = None

    def _shutdown(self) -> None:
        now_monotonic = time.monotonic()
        elapsed = max(0.0, now_monotonic - self._last_event_monotonic)
        self._handle_event_window(
            app_name=self._current_app,
            duration=elapsed,
            app_changed=False,
        )
        self._flush_pending_event(force=True)
        logging.info("System collector stopped")

    def _get_active_app_name(self) -> str:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return "unknown"

        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return "unknown"

        process_name = "unknown"
        try:
            process_name = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = "unknown"

        if "." in process_name:
            process_name = process_name.rsplit(".", maxsplit=1)[0]
        return process_name or "unknown"
