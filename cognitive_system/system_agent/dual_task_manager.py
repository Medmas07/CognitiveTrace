"""System-level dual-task probe using tkinter — no browser involvement required."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass


@dataclass
class DualTaskResult:
    probe_id: str
    reaction_time_ms: float
    success: bool
    miss: bool
    error: bool


class DualTaskManager:
    """
    Shows a topmost OS window with a click target.
    run_probe() blocks the calling thread until the user clicks or the
    timeout fires, then returns a DualTaskResult.
    """

    _WINDOW_WIDTH = 240
    _WINDOW_HEIGHT = 160
    _SCREEN_MARGIN = 24

    def __init__(self) -> None:
        self._last_position: tuple[int, int] | None = None

    def _random_position(self, screen_width: int, screen_height: int) -> tuple[int, int]:
        x_min = 0 if screen_width <= self._WINDOW_WIDTH + self._SCREEN_MARGIN * 2 else self._SCREEN_MARGIN
        y_min = 0 if screen_height <= self._WINDOW_HEIGHT + self._SCREEN_MARGIN * 2 else self._SCREEN_MARGIN
        x_max = max(x_min, screen_width - self._WINDOW_WIDTH - self._SCREEN_MARGIN)
        y_max = max(y_min, screen_height - self._WINDOW_HEIGHT - self._SCREEN_MARGIN)

        position = (random.randint(x_min, x_max), random.randint(y_min, y_max))
        for _ in range(8):
            if position != self._last_position:
                break
            position = (random.randint(x_min, x_max), random.randint(y_min, y_max))
        self._last_position = position
        return position

    def run_probe(self, probe_id: str, timeout_ms: int = 3000) -> DualTaskResult:
        result: dict = {
            "reaction_time_ms": 0.0,
            "success": False,
            "miss": False,
            "error": False,
        }
        done = threading.Event()

        def _run_ui() -> None:
            try:
                import tkinter as tk
            except ImportError:
                result["error"] = True
                done.set()
                return

            root = tk.Tk()
            root.title("Dual Task")
            # Always on top of every other window
            root.attributes("-topmost", True)
            root.resizable(False, False)
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x, y = self._random_position(sw, sh)
            root.geometry(f"{self._WINDOW_WIDTH}x{self._WINDOW_HEIGHT}+{x}+{y}")
            root.configure(bg="#0c1223")

            start_ns = time.perf_counter_ns()

            tk.Label(
                root,
                text="Click the button as fast as possible!",
                wraplength=210,
                bg="#0c1223",
                fg="#dcefff",
                font=("Arial", 10, "bold"),
            ).pack(pady=16)

            def on_click() -> None:
                elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
                result["reaction_time_ms"] = round(elapsed_ms, 2)
                result["success"] = True
                done.set()
                try:
                    root.destroy()
                except Exception:
                    pass

            tk.Button(
                root,
                text="CLICK",
                width=8,
                height=2,
                bg="#25c4f5",
                fg="#062035",
                font=("Arial", 11, "bold"),
                relief="flat",
                cursor="hand2",
                command=on_click,
            ).pack()

            def on_timeout() -> None:
                if not done.is_set():
                    result["miss"] = True
                    done.set()
                    try:
                        root.destroy()
                    except Exception:
                        pass

            root.after(timeout_ms, on_timeout)
            root.mainloop()

        t = threading.Thread(target=_run_ui, daemon=True)
        t.start()
        # Wait slightly beyond the probe timeout to allow the UI to close cleanly
        done.wait(timeout=(timeout_ms / 1000) + 1.0)
        t.join(timeout=0.5)

        return DualTaskResult(
            probe_id=probe_id,
            reaction_time_ms=result["reaction_time_ms"],
            success=result["success"],
            miss=result["miss"],
            error=result["error"],
        )
