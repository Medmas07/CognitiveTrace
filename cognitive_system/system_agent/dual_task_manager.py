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
    probe_left_px: int
    probe_top_px: int


class DualTaskManager:
    """
    Shows a topmost OS window with a click target.
    run_probe() blocks the calling thread until the user clicks or the
    timeout fires, then returns a DualTaskResult.
    """

    def __init__(self) -> None:
        self._rng = random.Random()

    def run_probe(
        self,
        probe_id: str,
        timeout_ms: int = 3000,
        *,
        randomize_position: bool = True,
    ) -> DualTaskResult:
        result: dict = {
            "reaction_time_ms": 0.0,
            "success": False,
            "miss": False,
            "error": False,
            "probe_left_px": 0,
            "probe_top_px": 0,
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
            probe_width = 240
            probe_height = 160
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            if randomize_position:
                x, y = self._random_probe_position(sw, sh, probe_width, probe_height)
            else:
                x = max(0, sw // 2 - probe_width // 2)
                y = max(0, sh // 2 - probe_height // 2)
            result["probe_left_px"] = x
            result["probe_top_px"] = y
            root.geometry(f"{probe_width}x{probe_height}+{x}+{y}")
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
            probe_left_px=result["probe_left_px"],
            probe_top_px=result["probe_top_px"],
        )

    def _random_probe_position(
        self,
        screen_width: int,
        screen_height: int,
        probe_width: int,
        probe_height: int,
    ) -> tuple[int, int]:
        margin_px = 48
        max_x = max(margin_px, screen_width - probe_width - margin_px)
        max_y = max(margin_px, screen_height - probe_height - margin_px)
        min_x = min(margin_px, max_x)
        min_y = min(margin_px, max_y)
        return (
            self._rng.randint(min_x, max_x),
            self._rng.randint(min_y, max_y),
        )
