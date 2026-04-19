from __future__ import annotations

MIN_DURATION_SECONDS = 1.0


def should_drop_event(duration_seconds: float) -> bool:
    """Behavioral filtering only: very short transitions are treated as system noise."""
    return duration_seconds < MIN_DURATION_SECONDS


def classify_event_type(duration_seconds: float, app_changed: bool) -> str:
    _ = duration_seconds
    if app_changed:
        return "switch"
    return "focus"
