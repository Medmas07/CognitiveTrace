"""
Tkinter GUI for browsing session temporal graphs in a grid of session cards.

Each card represents one session and contains:
- a compact session summary
- a mini directed graph preview
- a details button for a larger view with nodes/edges tables

The viewer rebuilds graph data in memory from raw behavior events so it can
switch between app/domain/url node levels without depending on precomputed
graph exports.
"""
from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from .graph_builder import GraphBuilder, NODE_LEVEL

LOGGER = logging.getLogger(__name__)

_CARD_BG = "#f7f9fc"
_CARD_BORDER = "#d8deea"
_TEXT = "#243447"
_MUTED = "#5d6b82"
_ACCENT = "#2f74c0"
_EDGE = "#8aa3c7"
_EMPTY_BG = "#eef3fb"
_NODE_PALETTE = [
    "#73a9ff",
    "#7cd6cf",
    "#ffb86c",
    "#f78fb3",
    "#9d79ff",
    "#95d36e",
]


@dataclass
class SessionGraphData:
    """In-memory representation of one session graph."""

    session_id: str
    session_dir: Path
    node_level: str
    nodes_df: pd.DataFrame
    edges_df: pd.DataFrame
    temporal_edges_df: pd.DataFrame
    events_df: pd.DataFrame
    error: Optional[str] = None

    @property
    def state_count(self) -> int:
        return int(len(self.nodes_df))

    @property
    def edge_count(self) -> int:
        return int(len(self.edges_df))

    @property
    def temporal_count(self) -> int:
        return int(len(self.temporal_edges_df))

    @property
    def event_count(self) -> int:
        return int(len(self.events_df))

    @property
    def duration_seconds(self) -> float:
        if self.events_df.empty or "duration_ms" not in self.events_df.columns:
            return 0.0
        return float(pd.to_numeric(self.events_df["duration_ms"], errors="coerce").fillna(0).sum() / 1000.0)


def discover_sessions(data_dir: Path) -> list[Path]:
    """Return session directories sorted newest-first by name."""
    if not data_dir.exists():
        return []
    session_dirs = [
        path
        for path in data_dir.iterdir()
        if path.is_dir() and (path / "raw" / "behavior.csv").exists()
    ]
    return sorted(session_dirs, key=lambda path: path.name, reverse=True)


def load_session_graph(session_dir: Path, node_level: str) -> SessionGraphData:
    """Build one session graph from raw behavior.csv."""
    behavior_path = session_dir / "raw" / "behavior.csv"
    if not behavior_path.exists():
        return SessionGraphData(
            session_id=session_dir.name,
            session_dir=session_dir,
            node_level=node_level,
            nodes_df=pd.DataFrame(),
            edges_df=pd.DataFrame(),
            temporal_edges_df=pd.DataFrame(),
            events_df=pd.DataFrame(),
            error="Missing raw/behavior.csv",
        )

    try:
        behavior_df = pd.read_csv(behavior_path, low_memory=False)
        builder = GraphBuilder(node_level=node_level)
        events_df, nodes_df, edges_df, temporal_edges_df = builder.build(behavior_df)
        return SessionGraphData(
            session_id=session_dir.name,
            session_dir=session_dir,
            node_level=node_level,
            nodes_df=nodes_df,
            edges_df=edges_df,
            temporal_edges_df=temporal_edges_df,
            events_df=events_df,
        )
    except Exception as exc:
        LOGGER.exception("Failed to load graph for session %s", session_dir.name)
        return SessionGraphData(
            session_id=session_dir.name,
            session_dir=session_dir,
            node_level=node_level,
            nodes_df=pd.DataFrame(),
            edges_df=pd.DataFrame(),
            temporal_edges_df=pd.DataFrame(),
            events_df=pd.DataFrame(),
            error=str(exc),
        )


class SessionGraphViewer:
    """Grid-based Tkinter viewer for session graphs."""

    def __init__(
        self,
        data_dir: Path,
        node_level: str = "app",
        columns: int = 2,
        card_width: int = 360,
        card_height: int = 240,
    ) -> None:
        self.data_dir = data_dir
        self.columns = max(1, int(columns))
        self.card_width = max(260, int(card_width))
        self.card_height = max(180, int(card_height))
        self._session_graphs: list[SessionGraphData] = []

        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:
            raise RuntimeError("tkinter is required to run the graph viewer") from exc

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title("Session Temporal Graph Viewer")
        self.root.configure(bg="#edf2f9")
        self.root.geometry("1220x840")

        self.node_level_var = tk.StringVar(value=node_level)
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready")
        self.columns_var = tk.IntVar(value=self.columns)

        self._build_layout()
        self.root.after(50, self.refresh)

    def _build_layout(self) -> None:
        tk = self.tk
        ttk = self.ttk

        outer = tk.Frame(self.root, bg="#edf2f9")
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg="#edf2f9", padx=18, pady=14)
        header.pack(fill="x")

        title = tk.Label(
            header,
            text="Temporal Session Graphs",
            bg="#edf2f9",
            fg=_TEXT,
            font=("Segoe UI", 17, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = tk.Label(
            header,
            text="Each card is one session. Graph nodes come from app/domain/url states, never windows.",
            bg="#edf2f9",
            fg=_MUTED,
            font=("Segoe UI", 10),
        )
        subtitle.grid(row=1, column=0, columnspan=8, sticky="w", pady=(4, 10))

        ttk.Label(header, text="Node level").grid(row=2, column=0, sticky="w")
        node_level_box = ttk.Combobox(
            header,
            textvariable=self.node_level_var,
            values=NODE_LEVEL,
            width=12,
            state="readonly",
        )
        node_level_box.grid(row=2, column=1, padx=(8, 16), sticky="w")
        node_level_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Label(header, text="Search").grid(row=2, column=2, sticky="w")
        search_entry = ttk.Entry(header, textvariable=self.search_var, width=28)
        search_entry.grid(row=2, column=3, padx=(8, 16), sticky="w")
        search_entry.bind("<KeyRelease>", lambda _event: self.render_cards())

        ttk.Label(header, text="Columns").grid(row=2, column=4, sticky="w")
        columns_box = ttk.Combobox(
            header,
            textvariable=self.columns_var,
            values=[1, 2, 3, 4],
            width=5,
            state="readonly",
        )
        columns_box.grid(row=2, column=5, padx=(8, 16), sticky="w")
        columns_box.bind("<<ComboboxSelected>>", lambda _event: self.render_cards())

        refresh_btn = ttk.Button(header, text="Refresh", command=self.refresh)
        refresh_btn.grid(row=2, column=6, sticky="w")

        status = tk.Label(
            header,
            textvariable=self.status_var,
            bg="#edf2f9",
            fg=_MUTED,
            font=("Segoe UI", 10),
        )
        status.grid(row=2, column=7, padx=(16, 0), sticky="e")

        table_frame = tk.Frame(outer, bg="#edf2f9", padx=14, pady=14)
        table_frame.pack(fill="both", expand=True, pady=(0, 14))

        self.canvas = tk.Canvas(
            table_frame,
            bg="#edf2f9",
            highlightthickness=0,
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.grid_frame = tk.Frame(self.canvas, bg="#edf2f9")
        self.grid_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        self.grid_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_frame_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.grid_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def refresh(self) -> None:
        node_level = self.node_level_var.get().strip() or "app"
        session_dirs = discover_sessions(self.data_dir)

        if not session_dirs:
            self._session_graphs = []
            self.status_var.set(f"No sessions found in {self.data_dir}")
            self.render_cards()
            return

        self.status_var.set(f"Loading {len(session_dirs)} sessions...")
        self.root.update_idletasks()

        self._session_graphs = [
            load_session_graph(session_dir, node_level=node_level)
            for session_dir in session_dirs
        ]
        self.status_var.set(f"Loaded {len(self._session_graphs)} sessions at node level '{node_level}'")
        self.render_cards()

    def render_cards(self) -> None:
        tk = self.tk
        search_text = self.search_var.get().strip().lower()
        columns = max(1, int(self.columns_var.get()))

        for child in self.grid_frame.winfo_children():
            child.destroy()

        filtered = [
            item
            for item in self._session_graphs
            if not search_text
            or search_text in item.session_id.lower()
            or search_text in item.node_level.lower()
        ]

        if not filtered:
            empty = tk.Label(
                self.grid_frame,
                text="No sessions match the current filter.",
                bg="#edf2f9",
                fg=_MUTED,
                font=("Segoe UI", 12),
                padx=20,
                pady=30,
            )
            empty.grid(row=0, column=0, sticky="w")
            self._on_frame_configure()
            return

        for col in range(columns):
            self.grid_frame.grid_columnconfigure(col, weight=1, uniform="session_col")

        for index, session_graph in enumerate(filtered):
            row = index // columns
            col = index % columns
            card = self._build_session_card(self.grid_frame, session_graph)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        self._on_frame_configure()

    def _build_session_card(self, parent, session_graph: SessionGraphData):
        tk = self.tk
        ttk = self.ttk

        card = tk.Frame(
            parent,
            bg=_CARD_BG,
            highlightbackground=_CARD_BORDER,
            highlightthickness=1,
            bd=0,
            padx=12,
            pady=12,
        )

        title = tk.Label(
            card,
            text=session_graph.session_id,
            bg=_CARD_BG,
            fg=_TEXT,
            anchor="w",
            justify="left",
            font=("Segoe UI", 11, "bold"),
        )
        title.pack(fill="x")

        meta = tk.Label(
            card,
            text=(
                f"states: {session_graph.state_count}   "
                f"edges: {session_graph.edge_count}   "
                f"transitions: {session_graph.temporal_count}   "
                f"events: {session_graph.event_count}"
            ),
            bg=_CARD_BG,
            fg=_MUTED,
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        )
        meta.pack(fill="x", pady=(4, 2))

        duration = tk.Label(
            card,
            text=f"node level: {session_graph.node_level}   total duration: {session_graph.duration_seconds:.2f}s",
            bg=_CARD_BG,
            fg=_MUTED,
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        )
        duration.pack(fill="x", pady=(0, 8))

        preview = tk.Canvas(
            card,
            width=self.card_width,
            height=self.card_height,
            bg=_EMPTY_BG,
            highlightthickness=0,
        )
        preview.pack(fill="both", expand=False)
        self._draw_graph(preview, session_graph, self.card_width, self.card_height)

        footer = tk.Frame(card, bg=_CARD_BG)
        footer.pack(fill="x", pady=(8, 0))

        if session_graph.error:
            error_label = tk.Label(
                footer,
                text=f"Error: {session_graph.error}",
                bg=_CARD_BG,
                fg="#b23c3c",
                anchor="w",
                justify="left",
                font=("Segoe UI", 9),
            )
            error_label.pack(side="left", fill="x", expand=True)
        else:
            edge_label = tk.Label(
                footer,
                text=self._top_edge_summary(session_graph),
                bg=_CARD_BG,
                fg=_MUTED,
                anchor="w",
                justify="left",
                font=("Segoe UI", 9),
            )
            edge_label.pack(side="left", fill="x", expand=True)

        ttk.Button(
            footer,
            text="Details",
            command=lambda sg=session_graph: self._open_details(sg),
        ).pack(side="right")

        return card

    def _draw_graph(self, canvas, session_graph: SessionGraphData, width: int, height: int) -> None:
        tk = self.tk
        canvas.delete("all")

        if session_graph.error:
            canvas.create_text(
                width / 2,
                height / 2,
                text=f"Failed to load graph\n{session_graph.error}",
                fill="#b23c3c",
                font=("Segoe UI", 10),
                justify="center",
            )
            return

        if session_graph.nodes_df.empty:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No valid events for this session",
                fill=_MUTED,
                font=("Segoe UI", 10),
            )
            return

        node_ids = session_graph.nodes_df["node_id"].astype(str).tolist()
        positions = self._compute_positions(node_ids, width, height)

        max_count = 1
        if not session_graph.edges_df.empty and "transition_count" in session_graph.edges_df.columns:
            max_count = max(1, int(session_graph.edges_df["transition_count"].max()))

        for edge in session_graph.edges_df.itertuples(index=False):
            source = str(edge.source)
            target = str(edge.target)
            transition_count = int(edge.transition_count)
            x1, y1 = positions[source]
            x2, y2 = positions[target]
            line_width = 1 + (4 * transition_count / max_count)

            if source == target:
                loop_r = 18
                canvas.create_arc(
                    x1 - loop_r,
                    y1 - loop_r - 24,
                    x1 + loop_r,
                    y1 + loop_r - 2,
                    start=30,
                    extent=300,
                    style=tk.ARC,
                    width=line_width,
                    outline=_EDGE,
                )
                canvas.create_text(
                    x1,
                    y1 - 34,
                    text=str(transition_count),
                    fill=_ACCENT,
                    font=("Segoe UI", 8, "bold"),
                )
            else:
                canvas.create_line(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=_EDGE,
                    width=line_width,
                    arrow=tk.LAST,
                    smooth=True,
                )
                mx = (x1 + x2) / 2
                my = (y1 + y2) / 2
                canvas.create_rectangle(
                    mx - 9,
                    my - 8,
                    mx + 9,
                    my + 8,
                    fill="#ffffff",
                    outline="",
                )
                canvas.create_text(
                    mx,
                    my,
                    text=str(transition_count),
                    fill=_ACCENT,
                    font=("Segoe UI", 8, "bold"),
                )

        radius = 20
        for index, node_id in enumerate(node_ids):
            x, y = positions[node_id]
            color = _NODE_PALETTE[index % len(_NODE_PALETTE)]
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=color,
                outline="#ffffff",
                width=2,
            )
            canvas.create_text(
                x,
                y + radius + 12,
                text=_truncate(node_id, 16),
                fill=_TEXT,
                font=("Segoe UI", 8),
                width=96,
                justify="center",
            )

    def _compute_positions(self, node_ids: list[str], width: int, height: int) -> dict[str, tuple[float, float]]:
        if not node_ids:
            return {}
        if len(node_ids) == 1:
            return {node_ids[0]: (width / 2, height / 2 - 8)}

        cx = width / 2
        cy = height / 2 - 6
        graph_radius = min(width, height) * 0.31
        positions: dict[str, tuple[float, float]] = {}

        for idx, node_id in enumerate(node_ids):
            angle = (2 * math.pi * idx / len(node_ids)) - (math.pi / 2)
            x = cx + (graph_radius * math.cos(angle))
            y = cy + (graph_radius * math.sin(angle))
            positions[node_id] = (x, y)

        return positions

    def _top_edge_summary(self, session_graph: SessionGraphData) -> str:
        if session_graph.edges_df.empty:
            return "No transitions"

        edge = (
            session_graph.edges_df
            .sort_values(["transition_count", "total_duration"], ascending=[False, False])
            .iloc[0]
        )
        return f"Top transition: {_truncate(str(edge['source']), 14)} -> {_truncate(str(edge['target']), 14)}"

    def _open_details(self, session_graph: SessionGraphData) -> None:
        tk = self.tk
        ttk = self.ttk

        win = tk.Toplevel(self.root)
        win.title(f"Session Graph Details - {session_graph.session_id}")
        win.configure(bg="#eef3fb")
        win.geometry("1020x760")

        header = tk.Frame(win, bg="#eef3fb", padx=16, pady=14)
        header.pack(fill="x")

        tk.Label(
            header,
            text=session_graph.session_id,
            bg="#eef3fb",
            fg=_TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")

        tk.Label(
            header,
            text=(
                f"node level: {session_graph.node_level}   "
                f"states: {session_graph.state_count}   "
                f"aggregated edges: {session_graph.edge_count}   "
                f"temporal edges: {session_graph.temporal_count}   "
                f"events: {session_graph.event_count}"
            ),
            bg="#eef3fb",
            fg=_MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        graph_canvas = tk.Canvas(
            win,
            width=960,
            height=340,
            bg="#ffffff",
            highlightbackground=_CARD_BORDER,
            highlightthickness=1,
        )
        graph_canvas.pack(fill="x", padx=16, pady=(0, 12))
        self._draw_graph(graph_canvas, session_graph, 960, 340)

        tables = tk.Frame(win, bg="#eef3fb", padx=16, pady=16)
        tables.pack(fill="both", expand=True, pady=(0, 16))
        tables.grid_columnconfigure(0, weight=1)
        tables.grid_columnconfigure(1, weight=2)
        tables.grid_rowconfigure(0, weight=1)

        node_frame = tk.Frame(tables, bg="#eef3fb")
        node_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        edge_frame = tk.Frame(tables, bg="#eef3fb")
        edge_frame.grid(row=0, column=1, sticky="nsew")

        tk.Label(node_frame, text="Nodes", bg="#eef3fb", fg=_TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        node_tree = ttk.Treeview(node_frame, columns=("node_id", "node_type"), show="headings", height=16)
        node_tree.heading("node_id", text="node_id")
        node_tree.heading("node_type", text="node_type")
        node_tree.column("node_id", width=240, anchor="w")
        node_tree.column("node_type", width=90, anchor="center")
        node_tree.pack(fill="both", expand=True, pady=(6, 0))

        for row in session_graph.nodes_df.itertuples(index=False):
            node_tree.insert("", "end", values=(row.node_id, row.node_type))

        tk.Label(edge_frame, text="Edges", bg="#eef3fb", fg=_TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        edge_tree = ttk.Treeview(
            edge_frame,
            columns=("source", "target", "transition_count", "total_duration", "avg_duration"),
            show="headings",
            height=16,
        )
        for column in ("source", "target", "transition_count", "total_duration", "avg_duration"):
            edge_tree.heading(column, text=column)
        edge_tree.column("source", width=200, anchor="w")
        edge_tree.column("target", width=200, anchor="w")
        edge_tree.column("transition_count", width=110, anchor="center")
        edge_tree.column("total_duration", width=120, anchor="center")
        edge_tree.column("avg_duration", width=120, anchor="center")
        edge_tree.pack(fill="both", expand=True, pady=(6, 0))

        for row in session_graph.edges_df.itertuples(index=False):
            edge_tree.insert(
                "",
                "end",
                values=(
                    row.source,
                    row.target,
                    row.transition_count,
                    row.total_duration,
                    row.avg_duration,
                ),
            )

    def run(self) -> None:
        self.root.mainloop()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m feature_engineering.graph_viewer",
        description="Open a GUI to browse session temporal graphs.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to the data directory (default: cognitive_system/data/)",
    )
    parser.add_argument(
        "--node-level",
        default="app",
        choices=NODE_LEVEL,
        help="Initial graph node granularity: app, domain, or url.",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=2,
        help="Number of session cards per row.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    data_dir = (
        Path(args.data_dir)
        if args.data_dir
        else Path(__file__).resolve().parent.parent / "data"
    )

    viewer = SessionGraphViewer(
        data_dir=data_dir,
        node_level=args.node_level,
        columns=args.columns,
    )
    viewer.run()


if __name__ == "__main__":
    main()
