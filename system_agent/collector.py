from __future__ import annotations

import ctypes
import logging
import time
from typing import Optional, Tuple

import psutil

from filters import classify_event_type, should_drop_event
from influx_client import InfluxBatchClient, now_ns
from models import Event


class BehaviorCollector:
    """Collects app-level focus/switch events with duration only."""

    def __init__(
        self,
        influx_client: InfluxBatchClient,
        user_id: str = "u1",
        poll_interval: float = 0.5,
        emit_interval: float = 30.0,
        merge_flush_threshold: float = 30.0,
    ) -> None:
        self.influx_client = influx_client
        self.user_id = user_id
        self.poll_interval = poll_interval
        self.emit_interval = emit_interval
        self.merge_flush_threshold = merge_flush_threshold

        self._running = False
        self._current_app = "unknown"
        self._current_title = ""
        self._last_event_monotonic = 0.0
        self._next_emit_deadline = 0.0
        self._pending_event: Optional[Event] = None

        self._user32 = ctypes.windll.user32

    def request_stop(self) -> None:
        self._running = False

    def run_forever(self, session_minutes: Optional[float] = None) -> None:
        self._running = True

        self._current_app, self._current_title = self._get_active_window_info()
        self._last_event_monotonic = time.monotonic()
        self._next_emit_deadline = self._last_event_monotonic + self.emit_interval
        session_end_monotonic: Optional[float] = None
        if session_minutes is not None:
            session_end_monotonic = self._last_event_monotonic + (session_minutes * 60.0)

        if session_end_monotonic is None:
            logging.info("System collector started (no session limit)")
        else:
            logging.info(
                "System collector started (session_minutes=%.2f)",
                session_minutes,
            )

        try:
            while self._running:
                if (
                    session_end_monotonic is not None
                    and time.monotonic() >= session_end_monotonic
                ):
                    logging.info("Session duration reached; stopping collector")
                    self.request_stop()
                    continue

                self._poll_tick()
                time.sleep(self.poll_interval)
        finally:
            self._shutdown()

    def _poll_tick(self) -> None:
        now_monotonic = time.monotonic()
        active_app, active_title = self._get_active_window_info()
        app_changed = active_app != self._current_app
        elapsed = max(0.0, now_monotonic - self._last_event_monotonic)

        if app_changed:
            self._handle_event_window(
                app_name=self._current_app,
                window_title=self._current_title,
                duration=elapsed,
                app_changed=True,
            )
            self._current_app = active_app
            self._current_title = active_title
            self._last_event_monotonic = now_monotonic
            # Critical: app switch starts a new 30s window from this instant.
            self._next_emit_deadline = now_monotonic + self.emit_interval
            return

        self._current_title = active_title
        if now_monotonic >= self._next_emit_deadline:
            self._handle_event_window(
                app_name=self._current_app,
                window_title=self._current_title,
                duration=elapsed,
                app_changed=False,
            )
            self._last_event_monotonic = now_monotonic
            self._next_emit_deadline = now_monotonic + self.emit_interval

    def _handle_event_window(
        self,
        app_name: str,
        window_title: str,
        duration: float,
        app_changed: bool,
    ) -> None:
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
            window_title=window_title or "",
            user_id=self.user_id,
            source_type="app",
        )

        if event.event_type == "switch":
            self._flush_pending_event(force=True)
            # One user event must map to one Influx point.
            # Creating multiple points for a single transition breaks graph edges.
            self._log_event(event)
            self.influx_client.enqueue_line(event.to_line_protocol())
            return

        # Focus intervals from the same app are merged before write.
        # Writing each tiny slice separately would fragment sessions.
        if (
            self._pending_event
            and self._pending_event.app_name == event.app_name
            and self._pending_event.event_type == "focus"
        ):
            self._pending_event.duration += event.duration
            self._pending_event.timestamp = event.timestamp
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
        self._log_event(self._pending_event)
        self.influx_client.enqueue_line(self._pending_event.to_line_protocol())
        self._pending_event = None

    def _shutdown(self) -> None:
        now_monotonic = time.monotonic()
        elapsed = max(0.0, now_monotonic - self._last_event_monotonic)
        self._handle_event_window(
            app_name=self._current_app,
            window_title=self._current_title,
            duration=elapsed,
            app_changed=False,
        )
        self._flush_pending_event(force=True)
        logging.info("System collector stopped")

    def _log_event(self, event: Event) -> None:
        # Keep the Influx point minimal (duration-only field), but still expose
        # window/tab title in local logs so Chrome tab context is visible.
        logging.info(
            "event=%s app=%s duration=%.2fs title=%s",
            event.event_type,
            event.app_name,
            event.duration,
            (event.window_title or "")[:180],
        )

    def _get_active_window_info(self) -> Tuple[str, str]:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return "unknown", ""

        title_length = self._user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        self._user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        window_title = title_buffer.value.strip()

        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return "unknown", window_title

        process_name = "unknown"
        try:
            process_name = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = "unknown"

        if "." in process_name:
            process_name = process_name.rsplit(".", maxsplit=1)[0]
        return process_name or "unknown", window_title
