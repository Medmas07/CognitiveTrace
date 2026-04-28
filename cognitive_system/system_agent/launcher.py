from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import RuntimeConfig, build_default_runtime_config
from .dependency_validation import validate_runtime_dependencies
from .main import CognitiveSystemAgent


@dataclass
class LaunchDecision:
    confirmed: bool


class StartupLauncher:
    """Small default-config confirmation window for production-style launch."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._decision = LaunchDecision(confirmed=False)

    def show(self) -> bool:
        try:
            import tkinter as tk
        except ImportError:
            raise RuntimeError("tkinter is required for the desktop launcher.")

        root = tk.Tk()
        root.title("Cognitive Session Launcher")
        root.configure(bg="#edf3fb")
        root.geometry("620x520")
        root.resizable(False, False)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"620x520+{max(0, sw // 2 - 310)}+{max(0, sh // 2 - 260)}")

        shell = tk.Frame(root, bg="#edf3fb", padx=22, pady=20)
        shell.pack(fill="both", expand=True)

        tk.Label(
            shell,
            text="Cognitive Data Collection",
            bg="#edf3fb",
            fg="#203243",
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="w")

        tk.Label(
            shell,
            text="Default configuration is ready. Click Start Session to begin.",
            bg="#edf3fb",
            fg="#5f7285",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(6, 16))

        card = tk.Frame(shell, bg="#ffffff", padx=18, pady=18, highlightbackground="#d5deea", highlightthickness=1)
        card.pack(fill="both", expand=True)

        rows = [
            ("Mode", self.config.mode),
            ("Session duration", f"{self.config.session_duration_minutes} minutes"),
            ("CSV export", "Enabled" if self.config.csv_enabled else "Disabled"),
            ("InfluxDB export", "Enabled" if self.config.influx_enabled else "Disabled"),
            ("Dual task", "Enabled" if self.config.dual_task_enabled else "Disabled"),
            ("Questionnaire", "Enabled" if self.config.questionnaire_enabled else "Disabled"),
            ("Keyboard tracking", "Enabled" if self.config.keyboard_tracking_enabled else "Disabled"),
            ("Mouse tracking", "Enabled" if self.config.mouse_tracking_enabled else "Disabled"),
            ("Notifications", "Enabled" if self.config.notification_tracking_enabled else "Disabled"),
            ("System metrics", "Enabled" if self.config.system_metrics_enabled else "Disabled"),
            ("Timer overlay", "Enabled" if self.config.ui_overlay_enabled else "Disabled"),
            ("Data directory", str(self.config.data_dir)),
        ]

        for label, value in rows:
            row = tk.Frame(card, bg="#ffffff", pady=4)
            row.pack(fill="x")
            tk.Label(
                row,
                text=label,
                width=18,
                anchor="w",
                bg="#ffffff",
                fg="#31475d",
                font=("Segoe UI", 10, "bold"),
            ).pack(side="left")
            tk.Label(
                row,
                text=value,
                anchor="w",
                justify="left",
                bg="#ffffff",
                fg="#4f6478",
                font=("Segoe UI", 10),
                wraplength=360,
            ).pack(side="left", fill="x", expand=True)

        note = tk.Frame(shell, bg="#edf3fb", pady=14)
        note.pack(fill="x")

        tk.Label(
            note,
            text="After start, this window closes and the session timer overlay appears.",
            bg="#edf3fb",
            fg="#3d5369",
            font=("Segoe UI", 10),
        ).pack(anchor="w")
        tk.Label(
            note,
            text="When the session ends, the questionnaire opens in the browser if the extension is connected; otherwise it opens in the desktop app.",
            bg="#edf3fb",
            fg="#607188",
            font=("Segoe UI", 9),
            justify="left",
            wraplength=560,
        ).pack(anchor="w", pady=(6, 0))

        buttons = tk.Frame(shell, bg="#edf3fb", pady=6)
        buttons.pack(fill="x")

        def _cancel() -> None:
            self._decision.confirmed = False
            root.destroy()

        def _confirm() -> None:
            self._decision.confirmed = True
            root.destroy()

        tk.Button(
            buttons,
            text="Cancel",
            command=_cancel,
            bg="#d8e0ea",
            fg="#2c3d4f",
            relief="flat",
            padx=18,
            pady=9,
            font=("Segoe UI", 10),
            cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            buttons,
            text="Start Session",
            command=_confirm,
            bg="#2f7dd1",
            fg="white",
            activebackground="#2366ae",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=9,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", _cancel)
        root.mainloop()
        return self._decision.confirmed


def _show_error_dialog(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print(message)
        return

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Cognitive Session Launcher", message)
    root.destroy()


def run_launcher() -> int:
    try:
        config = build_default_runtime_config()
        validate_runtime_dependencies(config)
    except Exception as exc:
        _show_error_dialog(f"Startup failed:\n\n{exc}")
        return 1

    try:
        if not StartupLauncher(config).show():
            return 0
    except Exception as exc:
        _show_error_dialog(f"Could not open the launcher window:\n\n{exc}")
        return 1

    agent = CognitiveSystemAgent(config)
    try:
        asyncio.run(agent.run(wait_for_user_start=False))
    except KeyboardInterrupt:
        pass
    return 0


def main() -> None:
    raise SystemExit(run_launcher())
