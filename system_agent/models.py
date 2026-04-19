from __future__ import annotations

from dataclasses import dataclass


def _escape_measurement(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ")


def _escape_tag(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(" ", "\\ ")
        .replace("=", "\\=")
    )


def _format_float(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if "." not in text:
        text = f"{text}.0"
    return text


def _escape_field_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class Event:
    timestamp: int
    app_name: str
    event_type: str
    duration: float
    window_title: str = ""
    user_id: str = "u1"
    source_type: str = "app"
    measurement: str = "behavior_events"

    def to_line_protocol(self) -> str:
        tags = {
            "user_id": self.user_id,
            "source_type": self.source_type,
            "app_name": self.app_name or "unknown",
            "event_type": self.event_type,
        }
        tag_str = ",".join(
            f"{_escape_tag(str(key))}={_escape_tag(str(value))}"
            for key, value in tags.items()
        )
        duration = _format_float(max(0.0, self.duration))
        safe_title = _escape_field_string((self.window_title or "")[:240])
        fields = f'duration={duration},window_title="{safe_title}"'
        return f"{_escape_measurement(self.measurement)},{tag_str} {fields} {self.timestamp}"
