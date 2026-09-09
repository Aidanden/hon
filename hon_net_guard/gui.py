"""English Tkinter UI for HoN Net Guard (Windows + Linux)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .config import MAX_PING_SHARE, Settings
from .monitor import Snapshot, format_rate
from .stabilizer import HonNetGuard
from . import qos

# High-contrast palette (works on Fedora/Windows dark & light desktops)
BG = "#12161c"
CARD = "#1e2630"
CARD2 = "#263140"
TEXT = "#f2f5f8"
MUTED = "#a7b3c2"
ACCENT = "#f0c14b"
GREEN = "#2fd67b"
BTN_BG = "#3a4a5c"
BTN_BG_HOVER = "#4b5f75"
BTN_FG = "#ffffff"
ACCENT_BTN_BG = "#c9941a"
ACCENT_BTN_HOVER = "#e0a820"
ACCENT_BTN_FG = "#141414"
DANGER_BG = "#8b3a3a"
ENTRY_BG = "#0f1318"
WARN = "#ff8f6b"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"HoN Net Guard — {qos.platform_name()}")
        self.geometry("780x700")
        self.minsize(700, 620)
        self.configure(bg=BG)
        try:
            self.tk.call("tk", "scaling", 1.15)
        except tk.TclError:
            pass

        self.guard = HonNetGuard()
        self._build_style()
        self._build_ui()
        self.guard.monitor.on_update(self._on_snapshot)
        self.guard.start_monitor()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._refresh_status_bar)

    def _font(self, size: int = 10, bold: bool = False) -> tuple:
        if qos.is_windows():
            family = "Segoe UI"
        else:
            # Prefer fonts that render well on Fedora
            for candidate in ("Noto Sans", "DejaVu Sans", "Cantarell", "Sans"):
                family = candidate
                break
        return (family, size, "bold") if bold else (family, size)

    def _mono(self, size: int = 10) -> tuple:
        if qos.is_windows():
            return ("Consolas", size)
        return ("DejaVu Sans Mono", size)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=TEXT, font=self._font(10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card2.TFrame", background=CARD2)

        style.configure("TLabel", background=BG, foreground=TEXT, font=self._font(10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=self._font(10))
        style.configure(
            "Title.TLabel",
            background=BG,
            foreground=ACCENT,
            font=self._font(18, True),
        )
        style.configure(
            "Score.TLabel",
            background=CARD,
            foreground=GREEN,
            font=self._font(24, True),
        )
        style.configure(
            "Stat.TLabel",
            background=CARD,
            foreground=TEXT,
            font=self._mono(11),
        )
        style.configure(
            "Muted.TLabel",
            background=BG,
            foreground=MUTED,
            font=self._font(9),
        )
        style.configure(
            "CardMuted.TLabel",
            background=CARD,
            foreground=MUTED,
            font=self._font(9),
        )
        style.configure(
            "Warn.TLabel",
            background=CARD,
            foreground=WARN,
            font=self._font(10, True),
        )
        style.configure(
            "Section.TLabel",
            background=CARD,
            foreground=ACCENT,
            font=self._font(11, True),
        )

        style.configure(
            "TCheckbutton",
            background=CARD,
            foreground=TEXT,
            font=self._font(10),
            focuscolor=CARD,
        )
        style.map(
            "TCheckbutton",
            background=[("active", CARD), ("selected", CARD)],
            foreground=[("active", TEXT), ("selected", TEXT), ("disabled", MUTED)],
        )

        style.configure(
            "TEntry",
            fieldbackground=ENTRY_BG,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor="#445466",
            lightcolor="#445466",
            darkcolor="#445466",
            padding=6,
        )
        style.map(
            "TEntry",
            fieldbackground=[("focus", ENTRY_BG), ("!disabled", ENTRY_BG)],
            foreground=[("!disabled", TEXT)],
        )

        style.configure(
            "Horizontal.TScale",
            background=CARD,
            troughcolor=ENTRY_BG,
            bordercolor=CARD,
            lightcolor=GREEN,
            darkcolor=GREEN,
        )

        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor=ENTRY_BG,
            background=GREEN,
            bordercolor=CARD,
            lightcolor=GREEN,
            darkcolor=GREEN,
            thickness=16,
        )

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        primary: bool = False,
        danger: bool = False,
    ) -> tk.Button:
        if primary:
            bg, hover, fg = ACCENT_BTN_BG, ACCENT_BTN_HOVER, ACCENT_BTN_FG
        elif danger:
            bg, hover, fg = DANGER_BG, "#a44848", BTN_FG
        else:
            bg, hover, fg = BTN_BG, BTN_BG_HOVER, BTN_FG

        # Use classic raised buttons — flat ttk/tk buttons often vanish on Fedora themes.
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._font(11, bold=True),
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground="#8899aa",
            relief="raised",
            bd=3,
            padx=16,
            pady=10,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground="#ffffff",
            highlightcolor="#ffffff",
        )
        btn.bind("<Enter>", lambda _e, b=btn, h=hover: b.configure(bg=h, relief="raised"))
        btn.bind("<Leave>", lambda _e, b=btn, c=bg: b.configure(bg=c, relief="raised"))
        return btn
    def _priv_text(self) -> str:
        if qos.is_admin():
            return "Privileges: root/Admin OK" if qos.is_linux() else "Privileges: Administrator OK"
        if qos.is_linux():
            return "Privileges: normal — run with: sudo ./run_linux.sh"
        return "Privileges: normal — Run as Administrator required"

    def _build_ui(self) -> None:
        # 1) Pin action bar to the BOTTOM first — otherwise tall content pushes buttons off-screen.
        action_bar = tk.Frame(self, bg="#0a0d12", padx=12, pady=12)
        action_bar.pack(side="bottom", fill="x")
        tk.Label(
            action_bar,
            text="ACTIONS",
            bg="#0a0d12",
            fg=ACCENT,
            font=self._font(10, True),
        ).pack(anchor="w", pady=(0, 8))
        btns = tk.Frame(action_bar, bg="#0a0d12")
        btns.pack(fill="x")
        self._make_button(
            btns, "Enable Max Ping 100%", self._activate_max, primary=True
        ).pack(side="left", padx=(0, 8))
        self._make_button(btns, "Enable Normal", self._activate).pack(side="left", padx=(0, 8))
        self._make_button(btns, "Stop", self._deactivate, danger=True).pack(side="left", padx=(0, 8))
        self._make_button(btns, "Save", self._save_settings).pack(side="left")

        # 2) Main content fills remaining space above the action bar.
        outer = ttk.Frame(self, style="TFrame")
        outer.pack(side="top", fill="both", expand=True, padx=16, pady=(14, 8))

        # Header
        ttk.Label(outer, text="HoN Net Guard", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Stabilize ping and stop timeouts while playing Heroes of Newerth Reborn",
            style="Muted.TLabel",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(2, 6))
        self.admin_var = tk.StringVar(value=self._priv_text())
        ttk.Label(outer, textvariable=self.admin_var, style="Muted.TLabel").pack(anchor="w")

        # Score
        score_card = ttk.Frame(outer, style="Card.TFrame")
        score_card.pack(fill="x", pady=(12, 8))
        s_in = ttk.Frame(score_card, style="Card.TFrame")
        s_in.pack(fill="x", padx=14, pady=14)
        ttk.Label(s_in, text="PING SCORE", style="Section.TLabel").pack(anchor="w")
        self.score_var = tk.StringVar(value="Ping improvement: 0%")
        ttk.Label(s_in, textvariable=self.score_var, style="Score.TLabel").pack(
            anchor="w", pady=(4, 0)
        )
        self.score_bar = ttk.Progressbar(
            s_in,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="Green.Horizontal.TProgressbar",
        )
        self.score_bar.pack(fill="x", pady=(10, 6))
        self.score_detail = tk.StringVar(
            value="Enable Max Ping 100% mode to stabilize your connection"
        )
        ttk.Label(s_in, textvariable=self.score_detail, style="CardMuted.TLabel").pack(anchor="w")

        # Settings
        card = ttk.Frame(outer, style="Card.TFrame")
        card.pack(fill="x", pady=8)
        inner = ttk.Frame(card, style="Card.TFrame")
        inner.pack(fill="x", padx=14, pady=14)
        ttk.Label(inner, text="SETTINGS", style="Section.TLabel").pack(anchor="w", pady=(0, 8))

        self.link_var = tk.DoubleVar(value=self.guard.settings.link_mbps)
        share = (
            MAX_PING_SHARE if self.guard.settings.max_ping_mode else self.guard.settings.game_share
        )
        self.share_var = tk.DoubleVar(value=share * 100)
        self.throttle_label = tk.StringVar()
        self.max_ping_var = tk.BooleanVar(value=self.guard.settings.max_ping_mode)
        self.do_var = tk.BooleanVar(value=self.guard.settings.tame_delivery_optimization)
        self.dscp_var = tk.BooleanVar(value=self.guard.settings.mark_dscp)
        self._update_throttle_label()

        row1 = ttk.Frame(inner, style="Card.TFrame")
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="Your download speed (Mbps)", style="Card.TLabel").pack(side="left")
        ttk.Entry(row1, textvariable=self.link_var, width=10, justify="center").pack(side="right")

        row2 = ttk.Frame(inner, style="Card.TFrame")
        row2.pack(fill="x", pady=(10, 4))
        ttk.Label(row2, text="Bandwidth cap share %", style="Card.TLabel").pack(side="left")
        self.share_value = tk.StringVar(value=f"{int(self.share_var.get())}%")
        ttk.Label(row2, textvariable=self.share_value, style="Card.TLabel").pack(side="right")

        ttk.Scale(
            inner,
            from_=25,
            to=85,
            orient="horizontal",
            variable=self.share_var,
            command=self._on_share_move,
        ).pack(fill="x", pady=(2, 6))
        self.link_var.trace_add("write", lambda *_: self._update_throttle_label())

        ttk.Label(inner, textvariable=self.throttle_label, style="Stat.TLabel").pack(
            anchor="w", pady=(4, 8)
        )
        ttk.Checkbutton(
            inner,
            text="Max ping mode (more headroom + system latency tweaks)",
            variable=self.max_ping_var,
            command=self._on_max_toggle,
        ).pack(anchor="w", pady=2)

        if qos.is_windows():
            ttk.Checkbutton(
                inner,
                text="Disable Windows Update Delivery Optimization",
                variable=self.do_var,
            ).pack(anchor="w", pady=2)

        # Live stats
        stats = ttk.Frame(outer, style="Card.TFrame")
        stats.pack(fill="x", pady=8)
        s_inner = ttk.Frame(stats, style="Card.TFrame")
        s_inner.pack(fill="x", padx=14, pady=14)
        ttk.Label(s_inner, text="LIVE STATUS", style="Section.TLabel").pack(
            anchor="w", pady=(0, 8)
        )

        self.game_var = tk.StringVar(value="Game: not detected")
        self.down_var = tk.StringVar(value="Download: —")
        self.up_var = tk.StringVar(value="Upload: —")
        self.ping_var = tk.StringVar(value="Ping: —")
        self.warn_var = tk.StringVar(value="")

        for var in (self.game_var, self.down_var, self.up_var, self.ping_var):
            ttk.Label(s_inner, textvariable=var, style="Stat.TLabel").pack(anchor="w", pady=2)
        ttk.Label(s_inner, textvariable=self.warn_var, style="Warn.TLabel").pack(
            anchor="w", pady=(6, 0)
        )

        # Log
        ttk.Label(outer, text="Log", style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        log_wrap = tk.Frame(
            outer, bg="#0b0e12", highlightbackground="#334152", highlightthickness=1
        )
        log_wrap.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_wrap,
            height=5,
            bg="#0b0e12",
            fg="#d5deea",
            insertbackground="#d5deea",
            font=self._mono(9),
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
            highlightthickness=0,
            borderwidth=0,
        )
        scroll = ttk.Scrollbar(log_wrap, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._append_log("Buttons stay fixed at the bottom. Use «Enable Max Ping 100%» with admin/root.")
        if not qos.is_admin():
            self._append_log("Warning: without root/Admin the bandwidth cap cannot be applied.")

    def _on_share_move(self, _value: str) -> None:
        try:
            self.share_value.set(f"{int(float(self.share_var.get()))}%")
        except (tk.TclError, ValueError):
            pass
        self._update_throttle_label()

    def _on_max_toggle(self) -> None:
        if self.max_ping_var.get():
            self.share_var.set(MAX_PING_SHARE * 100)
            self.share_value.set(f"{int(MAX_PING_SHARE * 100)}%")
        self._update_throttle_label()

    def _update_throttle_label(self) -> None:
        try:
            link = float(self.link_var.get())
            share = float(self.share_var.get()) / 100.0
        except (tk.TclError, ValueError, TypeError):
            return
        tmp = Settings(link_mbps=link, game_share=share, max_ping_mode=self.max_ping_var.get())
        self.throttle_label.set(
            f"Expected cap: ~ {tmp.throttle_mbps():.1f} Mbps   |   Headroom ~ {link - tmp.throttle_mbps():.1f} Mbps"
        )

    def _read_settings_into_guard(self) -> None:
        try:
            self.guard.settings.link_mbps = max(1.0, float(self.link_var.get()))
        except (tk.TclError, ValueError):
            self.guard.settings.link_mbps = 20.0
        try:
            self.guard.settings.game_share = max(0.25, min(0.85, float(self.share_var.get()) / 100.0))
        except (tk.TclError, ValueError):
            self.guard.settings.game_share = 0.45
        self.guard.settings.tame_delivery_optimization = bool(self.do_var.get())
        self.guard.settings.mark_dscp = bool(self.dscp_var.get())
        self.guard.settings.max_ping_mode = bool(self.max_ping_var.get())

    def _save_settings(self) -> None:
        self._read_settings_into_guard()
        self.guard.settings.save()
        self._append_log("Settings saved.")

    def _run_activate(self, max_ping: bool) -> None:
        self._read_settings_into_guard()
        if max_ping:
            self.max_ping_var.set(True)
            self.share_var.set(MAX_PING_SHARE * 100)
            self.share_value.set(f"{int(MAX_PING_SHARE * 100)}%")
            self._read_settings_into_guard()
        self._append_log("Activating and measuring ping (a few seconds)...")
        self.update_idletasks()
        ok = self.guard.activate(max_ping=max_ping)
        for line in self.guard.status.history[-10:]:
            self._append_log(line)
        self._set_score(self.guard.status.live_score)
        if not ok and self.guard.status.last_error == "need admin":
            msg = (
                "Run with: sudo ./run_linux.sh"
                if qos.is_linux()
                else "Run as administrator."
            )
            messagebox.showwarning("Insufficient privileges", msg)

    def _activate_max(self) -> None:
        self._run_activate(True)

    def _activate(self) -> None:
        self._run_activate(False)

    def _deactivate(self) -> None:
        self.guard.deactivate()
        self._append_log(self.guard.status.message)
        self._set_score(0)

    def _set_score(self, value: float) -> None:
        value = max(0.0, min(100.0, value))
        self.score_bar["value"] = value
        self.score_var.set(f"Ping improvement: {value:.0f}%")
        if value >= 100:
            self.score_detail.set("Fully stable — no saturation, steady ping, no timeouts")
        elif value >= 70:
            self.score_detail.set("Strong improvement — keep the game open and watch the meter")
        elif value > 0:
            self.score_detail.set("Guard active — waiting for samples to stabilize")
        else:
            self.score_detail.set("Inactive")

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _on_snapshot(self, snap: Snapshot) -> None:
        self.after(0, lambda: self._apply_snapshot(snap))

    def _apply_snapshot(self, snap: Snapshot) -> None:
        if snap.game_found:
            names = ", ".join(sorted({p.name for p in snap.processes}))
            self.game_var.set(f"Game: running ({names})")
        else:
            self.game_var.set("Game: not detected — launch HoN Reborn")

        self.down_var.set(f"Download: {format_rate(snap.total_down_bps)}")
        self.up_var.set(f"Upload: {format_rate(snap.total_up_bps)}")

        if snap.ping_ok and snap.ping_ms is not None:
            self.ping_var.set(f"Ping ({self.guard.settings.ping_host}): {snap.ping_ms:.0f} ms")
        elif snap.ping_ok:
            self.ping_var.set(f"Ping ({self.guard.settings.ping_host}): OK")
        else:
            self.ping_var.set(f"Ping ({self.guard.settings.ping_host}): timeout / failed")

        if snap.saturating:
            self.warn_var.set("Link saturated — lower share % or enable Max Ping mode")
        elif not snap.ping_ok and snap.game_found:
            self.warn_var.set("Timeout detected — enable Max Ping 100%")
        else:
            self.warn_var.set("")

        score = self.guard.update_live_score(snap)
        self._set_score(score)
        self.guard.reapply_if_needed(snap)

    def _refresh_status_bar(self) -> None:
        self.admin_var.set(self._priv_text())
        self.after(2000, self._refresh_status_bar)

    def _on_close(self) -> None:
        try:
            self.guard.stop_monitor()
        finally:
            self.destroy()


def run_gui() -> None:
    app = App()
    app.mainloop()
