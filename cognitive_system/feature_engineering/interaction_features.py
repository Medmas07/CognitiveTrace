"""Reusable keyboard, mouse, and clipboard-derived interaction features."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

_EPS = 1e-9

KEYBOARD_METRIC_COLUMNS = [
    "keystroke_count",
    "printable_keystrokes",
    "keystroke_rate",
    "wpm",
    "ikd_ms",
    "ikd_mean_ms",
    "ikd_median_ms",
    "ikd_std_ms",
    "error_rate",
    "typing_burstiness",
    "burstiness",
    "pause_mean_duration",
    "pause_count",
    "pause_total_ms",
    "pause_max_ms",
    "pause_ratio",
    "pause_short_count",
    "pause_medium_count",
    "pause_long_count",
    "pause_pattern",
]

MOUSE_METRIC_COLUMNS = [
    "movement_speed_mean",
    "vitesse_mean",
    "vitesse_p95",
    "click_rate",
    "movement_entropy",
    "trajectory_entropy",
    "acceleration_mean",
    "acceleration_p95",
    "jerk_mean",
    "jerk_p95",
    "distance_px",
]

EDGE_CLIPBOARD_FEATURE_COLUMNS = [
    "copy_count",
    "cut_count",
    "paste_count",
    "copy_paste_count",
    "copy_paste_latency_mean_ms",
]

_CLICK_EVENT_TYPES = frozenset({"button_press", "mouse_click", "click", "mouse_press"})
_CTRL_KEYS = frozenset({"ctrl", "ctrl_l", "ctrl_r", "control", "control_l", "control_r"})
_SHIFT_KEYS = frozenset({"shift", "shift_l", "shift_r"})
_ERROR_KEYS = frozenset({"backspace", "delete", "del"})
_NON_PRINTABLE_KEYS = frozenset(
    {
        "alt",
        "alt_l",
        "alt_r",
        "caps_lock",
        "cmd",
        "cmd_l",
        "cmd_r",
        "ctrl",
        "ctrl_l",
        "ctrl_r",
        "delete",
        "down",
        "end",
        "enter",
        "esc",
        "home",
        "insert",
        "left",
        "menu",
        "page_down",
        "page_up",
        "right",
        "shift",
        "shift_l",
        "shift_r",
        "tab",
        "up",
    }
)


def compute_keyboard_metrics(
    df: pd.DataFrame | None,
    duration_s: float,
    pause_threshold_ms: float = 2_000.0,
) -> dict[str, float]:
    """Return typing dynamics for a window or a context-node slice."""

    metrics = zero_keyboard_metrics()
    if df is None or df.empty or duration_s <= 0:
        return metrics

    presses = df.copy()
    if "event_type" in presses.columns:
        event_type = presses["event_type"].fillna("").astype(str).str.lower()
        presses = presses[event_type.eq("key_press")].copy()
    if presses.empty or "timestamp" not in presses.columns:
        return metrics

    presses["timestamp"] = pd.to_numeric(presses["timestamp"], errors="coerce")
    presses = presses.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if presses.empty:
        return metrics

    keys = presses.get("key", pd.Series("", index=presses.index)).fillna("").astype(str).map(_normalize_key)
    timestamps = presses["timestamp"].to_numpy(dtype=float, copy=False)
    intervals = np.diff(timestamps) * 1_000.0 if len(timestamps) > 1 else np.array([], dtype=float)
    intervals = intervals[np.isfinite(intervals) & (intervals > 0)]

    printable_count = int(keys.map(_is_printable_key).sum())
    error_count = int(keys.isin(_ERROR_KEYS).sum())
    keystroke_count = int(len(presses))
    duration_min = max(float(duration_s) / 60.0, _EPS)

    ikd_mean = _mean(intervals)
    ikd_median = _median(intervals)
    ikd_std = _std(intervals)
    burstiness = float(ikd_std / (ikd_mean + _EPS)) if ikd_mean > 0 else 0.0

    short_pauses = intervals[(intervals >= 500.0) & (intervals < pause_threshold_ms)]
    medium_pauses = intervals[(intervals >= pause_threshold_ms) & (intervals < 5_000.0)]
    long_pauses = intervals[intervals >= 5_000.0]
    counted_pauses = intervals[intervals >= pause_threshold_ms]
    pause_total = float(counted_pauses.sum()) if counted_pauses.size else 0.0
    pause_pattern = (
        (len(short_pauses) + 2 * len(medium_pauses) + 3 * len(long_pauses))
        / max(1, len(intervals))
    )

    metrics.update(
        {
            "keystroke_count": float(keystroke_count),
            "printable_keystrokes": float(printable_count),
            "keystroke_rate": float(keystroke_count) / max(float(duration_s), _EPS),
            "wpm": float(printable_count) / 5.0 / duration_min,
            "ikd_ms": ikd_mean,
            "ikd_mean_ms": ikd_mean,
            "ikd_median_ms": ikd_median,
            "ikd_std_ms": ikd_std,
            "error_rate": float(error_count) / max(1.0, float(printable_count + error_count)),
            "typing_burstiness": burstiness,
            "burstiness": burstiness,
            "pause_mean_duration": _mean(counted_pauses),
            "pause_count": float(len(counted_pauses)),
            "pause_total_ms": pause_total,
            "pause_max_ms": float(counted_pauses.max()) if counted_pauses.size else 0.0,
            "pause_ratio": pause_total / max(float(duration_s) * 1_000.0, _EPS),
            "pause_short_count": float(len(short_pauses)),
            "pause_medium_count": float(len(medium_pauses)),
            "pause_long_count": float(len(long_pauses)),
            "pause_pattern": float(pause_pattern),
        }
    )
    return _round_metric_dict(metrics)


def compute_mouse_metrics(
    df: pd.DataFrame | None,
    duration_s: float,
    entropy_bins: int = 8,
) -> dict[str, float]:
    """Return movement dynamics for a window or a context-node slice."""

    metrics = zero_mouse_metrics()
    if df is None or df.empty or duration_s <= 0:
        return metrics

    mouse = df.copy()
    if "timestamp" not in mouse.columns:
        return metrics
    mouse["timestamp"] = pd.to_numeric(mouse["timestamp"], errors="coerce")
    mouse = mouse.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if mouse.empty:
        return metrics

    event_type = mouse.get("event_type", pd.Series("", index=mouse.index)).fillna("").astype(str).str.lower()
    moves = mouse[event_type.eq("mouse_move")].copy()
    clicks = mouse[event_type.isin(_CLICK_EVENT_TYPES)].copy()
    click_rate = float(len(clicks)) / max(float(duration_s), _EPS)

    if moves.empty:
        metrics["click_rate"] = round(click_rate, 6)
        return metrics

    timestamps = moves["timestamp"].to_numpy(dtype=float, copy=False)
    dx = pd.to_numeric(moves.get("delta_x", pd.Series(0.0, index=moves.index)), errors="coerce").fillna(0.0)
    dy = pd.to_numeric(moves.get("delta_y", pd.Series(0.0, index=moves.index)), errors="coerce").fillna(0.0)
    distance = np.hypot(dx.to_numpy(dtype=float, copy=False), dy.to_numpy(dtype=float, copy=False))
    total_distance = float(np.nansum(distance))

    speed = pd.to_numeric(moves.get("speed", pd.Series(np.nan, index=moves.index)), errors="coerce").to_numpy(
        dtype=float,
        copy=False,
    )
    dt = np.diff(timestamps, prepend=np.nan)
    computed_speed = np.divide(distance, dt, out=np.full_like(distance, np.nan, dtype=float), where=dt > 0.001)
    speed = np.where(np.isfinite(speed) & (speed >= 0), speed, computed_speed)
    valid_speed = speed[np.isfinite(speed) & (speed >= 0)]

    accel_abs = np.array([], dtype=float)
    jerk_abs = np.array([], dtype=float)
    if len(speed) > 1:
        speed_dt = np.diff(timestamps)
        speed_diff = np.diff(speed)
        valid = np.isfinite(speed_diff) & np.isfinite(speed_dt) & (speed_dt > 0.001)
        if valid.any():
            accel = speed_diff[valid] / speed_dt[valid]
            accel_abs = np.abs(accel[np.isfinite(accel)])
            if len(accel_abs) > 1:
                accel_dt = speed_dt[1:][valid[1:]] if len(valid) > 1 else np.array([], dtype=float)
                accel_diff = np.diff(accel)
                usable = min(len(accel_diff), len(accel_dt))
                if usable > 0:
                    jerk = accel_diff[:usable] / np.maximum(accel_dt[:usable], 0.001)
                    jerk_abs = np.abs(jerk[np.isfinite(jerk)])

    trajectory_entropy = _trajectory_entropy(dx.to_numpy(dtype=float), dy.to_numpy(dtype=float), entropy_bins)
    speed_mean = _mean(valid_speed)
    metrics.update(
        {
            "movement_speed_mean": speed_mean,
            "vitesse_mean": speed_mean,
            "vitesse_p95": _percentile(valid_speed, 95),
            "click_rate": click_rate,
            "movement_entropy": trajectory_entropy,
            "trajectory_entropy": trajectory_entropy,
            "acceleration_mean": _mean(accel_abs),
            "acceleration_p95": _percentile(accel_abs, 95),
            "jerk_mean": _mean(jerk_abs),
            "jerk_p95": _percentile(jerk_abs, 95),
            "distance_px": total_distance,
        }
    )
    return _round_metric_dict(metrics)


def detect_clipboard_actions(df: pd.DataFrame | None) -> pd.DataFrame:
    """Infer copy/cut/paste actions from key presses without reading clipboard content."""

    if df is None or df.empty or not {"timestamp", "key"}.issubset(df.columns):
        return pd.DataFrame(columns=["timestamp", "action", "key", "context"])

    keys = df.copy()
    keys["timestamp"] = pd.to_numeric(keys["timestamp"], errors="coerce")
    keys = keys.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if "event_type" not in keys.columns:
        keys["event_type"] = "key_press"

    ctrl_down = False
    shift_down = False
    rows: list[dict[str, Any]] = []
    for row in keys.to_dict("records"):
        event_type = str(row.get("event_type") or "").lower()
        key = _normalize_key(row.get("key"))

        if event_type == "key_press":
            if key in _CTRL_KEYS:
                ctrl_down = True
            if key in _SHIFT_KEYS:
                shift_down = True
            action = _clipboard_action_for_key(key, ctrl_down=ctrl_down, shift_down=shift_down)
            if action:
                rows.append(
                    {
                        "timestamp": float(row.get("timestamp", 0.0)),
                        "action": action,
                        "key": key,
                        "context": row.get("context", ""),
                    }
                )
        elif event_type == "key_release":
            if key in _CTRL_KEYS:
                ctrl_down = False
            if key in _SHIFT_KEYS:
                shift_down = False

    return pd.DataFrame(rows, columns=["timestamp", "action", "key", "context"])


def zero_keyboard_metrics() -> dict[str, float]:
    return dict.fromkeys(KEYBOARD_METRIC_COLUMNS, 0.0)


def zero_mouse_metrics() -> dict[str, float]:
    return dict.fromkeys(MOUSE_METRIC_COLUMNS, 0.0)


def zero_edge_clipboard_features() -> dict[str, float]:
    return dict.fromkeys(EDGE_CLIPBOARD_FEATURE_COLUMNS, 0.0)


def _clipboard_action_for_key(key: str, ctrl_down: bool, shift_down: bool) -> str:
    if key == "\x03" or (ctrl_down and key == "c") or (ctrl_down and key == "insert"):
        return "copy"
    if key == "\x18" or (ctrl_down and key == "x"):
        return "cut"
    if key == "\x16" or (ctrl_down and key == "v") or (shift_down and key == "insert"):
        return "paste"
    return ""


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("Key."):
        text = text[4:]
    return text.lower()


def _is_printable_key(key: str) -> bool:
    if key == "space":
        return True
    if key in _NON_PRINTABLE_KEYS or key in _ERROR_KEYS:
        return False
    if len(key) != 1:
        return False
    return ord(key) >= 32


def _trajectory_entropy(dx: np.ndarray, dy: np.ndarray, bins: int) -> float:
    nonzero = (dx != 0) | (dy != 0)
    if int(nonzero.sum()) <= 1:
        return 0.0
    angles = np.arctan2(dy[nonzero], dx[nonzero])
    counts, _ = np.histogram(angles, bins=max(2, int(bins)), range=(-math.pi, math.pi))
    total = counts.sum()
    if total <= 0:
        return 0.0
    p = counts[counts > 0] / total
    return float(-np.sum(p * np.log2(p + _EPS)))


def _mean(values: np.ndarray) -> float:
    values = values[np.isfinite(values)] if len(values) else values
    return float(values.mean()) if len(values) else 0.0


def _median(values: np.ndarray) -> float:
    values = values[np.isfinite(values)] if len(values) else values
    return float(np.median(values)) if len(values) else 0.0


def _std(values: np.ndarray) -> float:
    values = values[np.isfinite(values)] if len(values) else values
    return float(values.std()) if len(values) > 1 else 0.0


def _percentile(values: np.ndarray, percentile: float) -> float:
    values = values[np.isfinite(values)] if len(values) else values
    return float(np.percentile(values, percentile)) if len(values) else 0.0


def _round_metric_dict(metrics: dict[str, float]) -> dict[str, float]:
    rounded: dict[str, float] = {}
    for key, value in metrics.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        rounded[key] = round(number, 6)
    return rounded
