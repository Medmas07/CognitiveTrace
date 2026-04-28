"""
Node-level feature extraction for windowed behavioral graphs.

Each output row represents one node inside one window. The builder computes
lightweight graph-viewer-compatible metrics from the raw interaction streams.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from .graph_builder import GraphBuilder
from .windowing import WindowEngine

LOGGER = logging.getLogger(__name__)

NODE_FEATURE_COLUMNS = [
    "session_id",
    "window_id",
    "window_start",
    "window_end",
    "node_type",
    "node_id",
    "usage_time",
    "frequency",
    "scroll_intensity",
    "interaction_rate",
]


class NodeFeatureBuilder:
    """Build node-level features for each window."""

    def __init__(self) -> None:
        self._engine = WindowEngine()
        self._behavior_cleaner = GraphBuilder(node_level="app")

    def build(
        self,
        streams: Dict[str, pd.DataFrame],
        windows: pd.DataFrame,
        session_id: str,
    ) -> pd.DataFrame:
        if windows is None or windows.empty:
            return pd.DataFrame(columns=NODE_FEATURE_COLUMNS)

        behavior_df = streams.get("behavior", pd.DataFrame())
        cleaned_events = self._prepare_cleaned_behavior(behavior_df)
        scroll_events = self._prepare_scroll_events(behavior_df)
        interaction_events = self._prepare_interaction_events(
            cleaned_events=cleaned_events,
            keyboard_df=streams.get("keyboard", pd.DataFrame()),
            mouse_df=streams.get("mouse", pd.DataFrame()),
        )

        behavior_ts = cleaned_events["timestamp"].to_numpy(dtype=float, copy=False) if not cleaned_events.empty else np.array([])
        scroll_ts = scroll_events["timestamp"].to_numpy(dtype=float, copy=False) if not scroll_events.empty else np.array([])
        interaction_ts = (
            interaction_events["timestamp"].to_numpy(dtype=float, copy=False)
            if not interaction_events.empty else np.array([])
        )

        rows: list[pd.DataFrame] = []
        for win in windows.itertuples(index=False):
            ws = float(win.window_start)
            we = float(win.window_end)
            duration_s = max(we - ws, 0.001)

            behavior_slice = self._slice_by_timestamp(cleaned_events, behavior_ts, ws, we)
            scroll_slice = self._slice_by_timestamp(scroll_events, scroll_ts, ws, we)
            interaction_slice = self._slice_by_timestamp(interaction_events, interaction_ts, ws, we)

            window_rows = self._build_window_rows(
                session_id=session_id,
                window_id=str(win.window_id),
                window_start=ws,
                window_end=we,
                duration_s=duration_s,
                behavior_slice=behavior_slice,
                scroll_slice=scroll_slice,
                interaction_slice=interaction_slice,
            )
            if not window_rows.empty:
                rows.append(window_rows)

        if not rows:
            return pd.DataFrame(columns=NODE_FEATURE_COLUMNS)

        result = pd.concat(rows, ignore_index=True)
        ordered = result[NODE_FEATURE_COLUMNS].copy()
        ordered["usage_time"] = pd.to_numeric(ordered["usage_time"], errors="coerce").fillna(0.0).round(2)
        ordered["frequency"] = pd.to_numeric(ordered["frequency"], errors="coerce").fillna(0).astype(int)
        ordered["scroll_intensity"] = pd.to_numeric(ordered["scroll_intensity"], errors="coerce").fillna(0.0).round(4)
        ordered["interaction_rate"] = pd.to_numeric(ordered["interaction_rate"], errors="coerce").fillna(0.0).round(4)
        return ordered

    def export(self, node_features_df: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = node_features_df.copy() if node_features_df is not None else pd.DataFrame(columns=NODE_FEATURE_COLUMNS)
        for col in NODE_FEATURE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.Series(dtype=object)
        out[NODE_FEATURE_COLUMNS].to_csv(path, index=False)
        LOGGER.info("Node features: wrote %d rows to %s", len(out), path.name)

    def _build_window_rows(
        self,
        session_id: str,
        window_id: str,
        window_start: float,
        window_end: float,
        duration_s: float,
        behavior_slice: pd.DataFrame,
        scroll_slice: pd.DataFrame,
        interaction_slice: pd.DataFrame,
    ) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        for node_type in ("app", "domain", "url"):
            node_col = f"{node_type}_node_id"

            usage = self._group_metric(behavior_slice, node_col, "duration_ms", "sum")
            frequency = self._group_metric(behavior_slice, node_col, node_col, "size")
            scroll = self._group_metric(scroll_slice, node_col, "scroll_delta_y", "sum")
            interactions = self._group_metric(interaction_slice, node_col, node_col, "size")

            merged = pd.concat(
                [
                    usage.rename("usage_time"),
                    frequency.rename("frequency"),
                    scroll.rename("scroll_total"),
                    interactions.rename("interaction_count"),
                ],
                axis=1,
            ).fillna(0.0)
            if merged.empty:
                continue

            merged.index.name = node_col
            merged = merged.reset_index().rename(columns={node_col: "node_id"})
            merged["node_id"] = merged["node_id"].astype(str).str.strip()
            merged = merged[merged["node_id"].ne("")]
            merged = merged[merged["node_id"].ne("nan")]
            if merged.empty:
                continue

            merged["session_id"] = session_id
            merged["window_id"] = window_id
            merged["window_start"] = window_start
            merged["window_end"] = window_end
            merged["node_type"] = node_type
            merged["scroll_intensity"] = merged["scroll_total"].abs() / duration_s
            merged["interaction_rate"] = merged["interaction_count"] / duration_s
            parts.append(
                merged[
                    [
                        "session_id",
                        "window_id",
                        "window_start",
                        "window_end",
                        "node_type",
                        "node_id",
                        "usage_time",
                        "frequency",
                        "scroll_intensity",
                        "interaction_rate",
                    ]
                ]
            )

        if not parts:
            return pd.DataFrame(columns=NODE_FEATURE_COLUMNS)
        return pd.concat(parts, ignore_index=True)

    def _prepare_cleaned_behavior(self, behavior_df: pd.DataFrame) -> pd.DataFrame:
        cleaned = self._behavior_cleaner.clean_events(behavior_df)
        if cleaned.empty:
            return cleaned

        cleaned = cleaned.copy()
        cleaned["app_node_id"] = cleaned["app_name"].fillna("").astype(str).str.strip()
        cleaned["domain_node_id"] = cleaned["url"].map(_extract_domain).fillna("")
        cleaned["url_node_id"] = cleaned["url"].fillna("").astype(str).str.strip()
        cleaned["duration_ms"] = pd.to_numeric(cleaned["duration_ms"], errors="coerce").fillna(0.0)
        return cleaned.sort_values("timestamp").reset_index(drop=True)

    def _prepare_scroll_events(self, behavior_df: pd.DataFrame) -> pd.DataFrame:
        if behavior_df is None or behavior_df.empty or "timestamp" not in behavior_df.columns:
            return pd.DataFrame(columns=["timestamp", "app_node_id", "domain_node_id", "url_node_id", "scroll_delta_y"])

        scrolls = behavior_df.copy()
        scrolls["event_type"] = scrolls.get("event_type", pd.Series(dtype=str)).fillna("").astype(str)
        scrolls = scrolls[scrolls["event_type"].str.contains("scroll", case=False, na=False)].copy()
        if scrolls.empty:
            return pd.DataFrame(columns=["timestamp", "app_node_id", "domain_node_id", "url_node_id", "scroll_delta_y"])

        scrolls["timestamp"] = pd.to_numeric(scrolls["timestamp"], errors="coerce")
        scrolls = scrolls.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        scrolls["app_node_id"] = scrolls.get("app_name", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        scrolls["url_text"] = scrolls.get("url", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        scrolls["domain_node_id"] = scrolls["url_text"].map(_extract_domain).fillna("")
        scrolls["url_node_id"] = scrolls["url_text"]
        scrolls["scroll_delta_y"] = pd.to_numeric(
            scrolls.get("scroll_delta_y", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        return scrolls[["timestamp", "app_node_id", "domain_node_id", "url_node_id", "scroll_delta_y"]]

    def _prepare_interaction_events(
        self,
        cleaned_events: pd.DataFrame,
        keyboard_df: pd.DataFrame,
        mouse_df: pd.DataFrame,
    ) -> pd.DataFrame:
        frames = []

        if cleaned_events is not None and not cleaned_events.empty:
            frames.append(
                cleaned_events[
                    ["timestamp", "app_node_id", "domain_node_id", "url_node_id"]
                ].copy()
            )

        keyboard_events = self._prepare_context_events(keyboard_df)
        if not keyboard_events.empty:
            frames.append(keyboard_events)

        mouse_events = self._prepare_context_events(mouse_df)
        if not mouse_events.empty:
            frames.append(mouse_events)

        if not frames:
            return pd.DataFrame(columns=["timestamp", "app_node_id", "domain_node_id", "url_node_id"])

        result = pd.concat(frames, ignore_index=True)
        return result.sort_values("timestamp").reset_index(drop=True)

    def _prepare_context_events(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty or "timestamp" not in df.columns:
            return pd.DataFrame(columns=["timestamp", "app_node_id", "domain_node_id", "url_node_id"])

        base = df.copy()
        base["timestamp"] = pd.to_numeric(base["timestamp"], errors="coerce")
        base = base.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        context_series = base.get("context", pd.Series(dtype=str)).fillna("").astype(str)
        parsed_context = context_series.map(_safe_context_load)
        context_df = pd.json_normalize(parsed_context)

        base["app_node_id"] = context_df.get("active_app", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        url_text = context_df.get("url", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        domain_text = context_df.get("domain", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        base["url_node_id"] = url_text
        base["domain_node_id"] = domain_text.where(domain_text.ne(""), url_text.map(_extract_domain).fillna(""))
        return base[["timestamp", "app_node_id", "domain_node_id", "url_node_id"]]

    def _slice_by_timestamp(
        self,
        df: pd.DataFrame,
        ts_array: np.ndarray,
        win_start: float,
        win_end: float,
    ) -> pd.DataFrame:
        if df is None or df.empty or len(ts_array) == 0:
            return pd.DataFrame(columns=df.columns if df is not None else [])
        lo, hi = self._engine.window_slice_indices(ts_array, win_start, win_end)
        return df.iloc[lo:hi]

    @staticmethod
    def _group_metric(df: pd.DataFrame, node_col: str, value_col: str, agg: str) -> pd.Series:
        if df is None or df.empty or node_col not in df.columns:
            return pd.Series(dtype=float)
        valid = df[df[node_col].fillna("").astype(str).str.strip().ne("")].copy()
        if valid.empty:
            return pd.Series(dtype=float)
        if agg == "sum":
            return valid.groupby(node_col)[value_col].sum()
        if agg == "size":
            return valid.groupby(node_col)[value_col].size()
        raise ValueError(f"Unsupported aggregation: {agg}")


def _safe_context_load(value: str) -> dict:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _extract_domain(url: str) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    try:
        parsed = urlparse(text if "://" in text else f"//{text}")
        domain = (parsed.netloc or parsed.path.split("/", 1)[0]).strip().lower()
    except Exception:
        return None
    if not domain:
        return None
    return domain.split(":", 1)[0] or None
