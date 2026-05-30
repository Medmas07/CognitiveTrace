from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

LOGGER = logging.getLogger(__name__)

_DOT_COLORS = {
    "running": "#4caf50",
    "paused": "#ff9800",
    "idle": "#9e9e9e",
    "stopped": "#f44336",
}

_STATUS_LABELS = {
    "running": "REC",
    "paused": "PAUSED",
    "idle": "IDLE",
    "stopped": "STOPPED",
}


class UIOverlay:
    """Floating always-on-top draggable status overlay.

    Shows elapsed time, recording state, pause/resume, and stop controls.
    Double-click to expand a small control panel.
    Thread-safe: call update() from any thread.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._queue: queue.Queue = queue.Queue()
        self._root = None
        self._started = threading.Event()
        self._on_stop: Optional[Callable] = None
        self._on_pause_toggle: Optional[Callable] = None
        self._drag_x = 0
        self._drag_y = 0
        self._expanded = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(
        self,
        on_stop_requested: Optional[Callable] = None,
        on_pause_toggle_requested: Optional[Callable] = None,
    ) -> None:
        self._on_stop = on_stop_requested
        self._on_pause_toggle = on_pause_toggle_requested
        self._thread = threading.Thread(target=self._run, name="ui-overlay", daemon=True)
        self._thread.start()
        self._started.wait(timeout=3.0)

    def stop(self) -> None:
        self._queue.put(("quit",))
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def update(self, state: str, elapsed_sec: float, manual_paused: bool = False) -> None:
        """Thread-safe status update."""
        self._queue.put(("update", state, elapsed_sec, manual_paused))

    # ── tkinter thread ────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            LOGGER.warning("tkinter not available — UI overlay disabled")
            self._started.set()
            return

        root = tk.Tk()
        self._root = root
        root.title("")
        root.overrideredirect(True)   # borderless
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.94)
        root.configure(bg="#1a2332")

        # Position: bottom-right corner
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"+{sw - 215}+{sh - 82}")

        # ── Compact row ───────────────────────────────────────────────
        compact = tk.Frame(root, bg="#1a2332", padx=8, pady=6)
        compact.pack(fill="both", expand=True)

        self._dot = tk.Label(
            compact, text="●", font=("Segoe UI", 14), bg="#1a2332", fg="#9e9e9e",
        )
        self._dot.pack(side="left", padx=(0, 4))

        self._time_label = tk.Label(
            compact, text="00:00", font=("Consolas", 13, "bold"),
            bg="#1a2332", fg="#e8f4fc",
        )
        self._time_label.pack(side="left", padx=(0, 5))

        self._status_label = tk.Label(
            compact, text="IDLE", font=("Segoe UI", 9),
            bg="#1a2332", fg="#6b8ea8",
        )
        self._status_label.pack(side="left", padx=(0, 6))

        self._pause_btn = tk.Button(
            compact, text="||",
            font=("Segoe UI", 10, "bold"), bg="#2f7dd1", fg="white",
            activebackground="#2366ae", activeforeground="white",
            relief="flat", width=3, padx=0, pady=1,
            cursor="hand2", takefocus=False,
            command=self._request_pause_toggle,
        )
        self._pause_btn.pack(side="left")

        # ── Expanded panel (hidden until double-click) ────────────────
        self._expanded_frame = tk.Frame(root, bg="#1a2332", padx=8, pady=7)

        self._expanded_state = tk.Label(
            self._expanded_frame,
            text="Idle",
            font=("Segoe UI", 9),
            bg="#1a2332",
            fg="#b8cbe0",
            anchor="w",
        )
        self._expanded_state.pack(fill="x", pady=(0, 6))

        self._expanded_pause_btn = tk.Button(
            self._expanded_frame, text="Pause Session",
            font=("Segoe UI", 9, "bold"), bg="#2f7dd1", fg="white",
            activebackground="#2366ae", activeforeground="white",
            relief="flat", padx=8, pady=5,
            cursor="hand2", takefocus=False,
            command=self._request_pause_toggle,
        )
        self._expanded_pause_btn.pack(fill="x", pady=(0, 6))

        stop_btn = tk.Button(
            self._expanded_frame, text="Stop Session",
            font=("Segoe UI", 9), bg="#c0392b", fg="white",
            activebackground="#a93226", activeforeground="white",
            relief="flat", padx=8, pady=5,
            cursor="hand2", takefocus=False,
            command=self._request_stop,
        )
        stop_btn.pack(fill="x")

        # ── Wire drag + double-click on every visible widget ──────────
        for w in (compact, self._dot, self._time_label, self._status_label):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<Double-Button-1>", self._toggle_expand)

        self._started.set()
        self._poll_queue(root)
        root.mainloop()

    def _poll_queue(self, root) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                cmd = item[0]
                if cmd == "quit":
                    root.destroy()
                    return
                elif cmd == "update":
                    self._apply_update(item[1], item[2], item[3])
        except queue.Empty:
            pass
        root.after(200, lambda: self._poll_queue(root))

    def _apply_update(self, state: str, elapsed_sec: float, manual_paused: bool = False) -> None:
        elapsed = int(elapsed_sec)
        mins = elapsed // 60
        secs = elapsed % 60
        self._time_label.config(text=f"{mins:02d}:{secs:02d}")
        self._dot.config(fg=_DOT_COLORS.get(state, "#9e9e9e"))
        self._status_label.config(text=_STATUS_LABELS.get(state, state.upper()))
        if hasattr(self, "_pause_btn"):
            if state in {"idle", "stopped"}:
                self._pause_btn.config(text="||", state="disabled", bg="#4c5f73")
            else:
                self._pause_btn.config(
                    text=">" if manual_paused else "||",
                    state="normal",
                    bg="#ff9800" if manual_paused else "#2f7dd1",
                )
        if hasattr(self, "_expanded_pause_btn"):
            if state in {"idle", "stopped"}:
                self._expanded_pause_btn.config(
                    text="Pause Session",
                    state="disabled",
                    bg="#4c5f73",
                )
            else:
                self._expanded_pause_btn.config(
                    text="Resume Session" if manual_paused else "Pause Session",
                    state="normal",
                    bg="#ff9800" if manual_paused else "#2f7dd1",
                )
        if hasattr(self, "_expanded_state"):
            if manual_paused:
                state_text = "Paused by user"
            elif state == "running":
                state_text = "Recording"
            elif state == "paused":
                state_text = "Waiting for browser focus"
            else:
                state_text = _STATUS_LABELS.get(state, state.upper()).title()
            self._expanded_state.config(text=state_text)

    def _toggle_expand(self, _event=None) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._expanded_frame.pack(fill="x")
        else:
            self._expanded_frame.pack_forget()

    def _request_stop(self) -> None:
        if self._on_stop:
            self._on_stop()

    def _request_pause_toggle(self) -> None:
        if self._on_pause_toggle:
            self._on_pause_toggle()

    # ── Drag ──────────────────────────────────────────────────────────────────

    def _on_drag_start(self, event) -> None:
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _on_drag_motion(self, event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._root.geometry(f"+{x}+{y}")
