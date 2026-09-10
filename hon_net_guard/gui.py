"""Dashboard UI for HoN Net Guard (Windows + Linux).

Drawn mostly with tk.Canvas / tk.Frame so Fedora GTK themes cannot hide
button labels the way ttk widgets do.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .config import MAX_PING_SHARE, Settings
from .hon_tracker import format_activity as hon_format_activity
from .hon_tracker import format_duration, fix_hon_net_hogs, stop_hon_service
from .hogs import format_activity, kill_high_risk, kill_process
from .monitor import Snapshot, format_rate
from .stabilizer import HonNetGuard
from . import qos

# ---------------------------------------------------------------------------
# Palette — high contrast, gaming-utility look
# ---------------------------------------------------------------------------
BG = "#0b0f16"
BG2 = "#10161f"
CARD = "#161e2a"
CARD_HI = "#1c2634"
EDGE = "#2c3a4e"
TEXT = "#f3f6fa"
MUTED = "#8d9cb0"
GOLD = "#e8b84a"
GOLD_DK = "#c49222"
GOLD_FG = "#16120a"
GREEN = "#3ee08a"
GREEN_DK = "#1f8a52"
RED = "#e45d5d"
RED_DK = "#9b2e2e"
ORANGE = "#ff9a62"
CYAN = "#5ec8ff"
ENTRY = "#0c1118"
TRACK = "#0c1118"


def _round_fill(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, fill: str) -> list[int]:
    """Crisp rounded rectangle (4 discs + 2 bars). Returns item ids."""
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    ids = [
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=""),
        canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=""),
        canvas.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, fill=fill, outline=""),
        canvas.create_oval(x2 - 2 * r, y1, x2, y1 + 2 * r, fill=fill, outline=""),
        canvas.create_oval(x1, y2 - 2 * r, x1 + 2 * r, y2, fill=fill, outline=""),
        canvas.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2, fill=fill, outline=""),
    ]
    return ids


class PillButton(tk.Canvas):
    """Self-painted button — text is always drawn, never theme-dependent."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        font: tuple,
        variant: str = "default",
        width: int = 148,
        height: int = 40,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg") if str(parent.cget("bg")) else BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._text = text
        self._command = command
        self._font = font
        self._variant = variant
        self._bw = width
        self._bh = height
        self._hover = False
        self._down = False
        self._enabled = True
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _colors(self) -> tuple[str, str]:
        if not self._enabled:
            return "#2a3340", "#7a8796"
        press = self._down
        hover = self._hover
        if self._variant == "primary":
            bg = "#f0c45a" if hover or press else GOLD
            return (GOLD_DK if press else bg), GOLD_FG
        if self._variant == "danger":
            bg = "#f06a6a" if hover or press else RED
            return (RED_DK if press else bg), TEXT
        if self._variant == "ghost":
            bg = "#243044" if hover or press else CARD_HI
            return bg, TEXT
        bg = "#2b3a4d" if hover or press else "#223044"
        return bg, TEXT

    def _draw(self) -> None:
        self.delete("all")
        w = max(self._bw, int(self.winfo_width() or self._bw))
        h = max(self._bh, int(self.winfo_height() or self._bh))
        bg, fg = self._colors()
        _round_fill(self, 1, 1, w - 2, h - 2, 10, bg)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = False
        self._down = False
        self._draw()

    def _on_press(self, _e) -> None:
        if not self._enabled:
            return
        self._down = True
        self._draw()

    def _on_release(self, _e) -> None:
        if not self._enabled:
            return
        was = self._down
        self._down = False
        self._draw()
        if was and self._command:
            self._command()


class TabChip(tk.Canvas):
    def __init__(self, parent: tk.Misc, text: str, command, font: tuple, width: int = 170) -> None:
        super().__init__(
            parent, width=width, height=34, bg=BG, highlightthickness=0, bd=0, cursor="hand2"
        )
        self._text = text
        self._command = command
        self._font = font
        self._active = False
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self._command and self._command())
        self._draw()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._draw()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = int(self.cget("width")), int(self.cget("height"))
        if self._active:
            fill, fg = GOLD, GOLD_FG
        elif self._hover:
            fill, fg = "#243044", TEXT
        else:
            fill, fg = CARD, MUTED
        _round_fill(self, 1, 1, w - 2, h - 2, 8, fill)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)


class Chip(tk.Frame):
    def __init__(self, parent: tk.Misc, font: tuple) -> None:
        super().__init__(
            parent, bg=CARD, padx=10, pady=5, highlightbackground=EDGE, highlightthickness=1
        )
        self._dot = tk.Canvas(self, width=8, height=8, bg=CARD, highlightthickness=0, bd=0)
        self._dot.pack(side="left", padx=(0, 6))
        self._var = tk.StringVar(value="")
        self._lbl = tk.Label(self, textvariable=self._var, bg=CARD, fg=MUTED, font=font)
        self._lbl.pack(side="left")
        self._tone = "muted"

    def set(self, text: str, tone: str = "muted") -> None:
        self._var.set(text)
        colors = {
            "ok": GREEN,
            "warn": ORANGE,
            "bad": RED,
            "gold": GOLD,
            "info": CYAN,
            "muted": MUTED,
        }
        c = colors.get(tone, MUTED)
        self._dot.delete("all")
        self._dot.create_oval(1, 1, 7, 7, fill=c, outline="")
        self._lbl.configure(fg=c if tone in ("ok", "warn", "bad", "gold") else MUTED)
        self._tone = tone


class MetricTile(tk.Frame):
    def __init__(self, parent: tk.Misc, caption: str, fonts: dict[str, tuple]) -> None:
        super().__init__(parent, bg=CARD_HI, highlightbackground=EDGE, highlightthickness=1)
        pad = tk.Frame(self, bg=CARD_HI)
        pad.pack(fill="both", expand=True, padx=12, pady=10)
        tk.Label(pad, text=caption.upper(), bg=CARD_HI, fg=MUTED, font=fonts["tiny"]).pack(anchor="w")
        self.value = tk.StringVar(value="—")
        self._val = tk.Label(
            pad, textvariable=self.value, bg=CARD_HI, fg=TEXT, font=fonts["metric"]
        )
        self._val.pack(anchor="w", pady=(2, 0))
        self.hint = tk.StringVar(value="")
        self._hint = tk.Label(
            pad, textvariable=self.hint, bg=CARD_HI, fg=MUTED, font=fonts["tiny"]
        )
        self._hint.pack(anchor="w")

    def set(self, value: str, hint: str = "", tone: str = "normal") -> None:
        self.value.set(value)
        self.hint.set(hint)
        fg = {"good": GREEN, "warn": ORANGE, "bad": RED, "gold": GOLD}.get(tone, TEXT)
        self._val.configure(fg=fg)


class ScoreRing(tk.Canvas):
    def __init__(self, parent: tk.Misc, fonts: dict[str, tuple], size: int = 168) -> None:
        super().__init__(
            parent, width=size, height=size, bg=CARD, highlightthickness=0, bd=0
        )
        self._fonts = fonts
        self._size = size
        self._value = 0.0
        self._subtitle = "Inactive"
        self._draw()

    def set(self, value: float, subtitle: str) -> None:
        self._value = max(0.0, min(100.0, value))
        self._subtitle = subtitle
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        s = self._size
        pad = 16
        cx = cy = s / 2
        width = 12
        track = "#0e1620"
        pct = self._value / 100.0
        if pct >= 0.99:
            arc = GREEN
        elif pct >= 0.7:
            arc = GOLD
        elif pct > 0:
            arc = CYAN
        else:
            arc = EDGE

        self.create_oval(pad, pad, s - pad, s - pad, outline=track, width=width)
        if pct > 0.002:
            # Tk arcs: 90° = 12 o'clock, negative extent = clockwise
            extent = max(-359.9, -pct * 359.9)
            self.create_arc(
                pad,
                pad,
                s - pad,
                s - pad,
                start=90,
                extent=extent,
                style="arc",
                outline=arc,
                width=width,
            )
        self.create_text(cx, cy - 8, text=f"{self._value:.0f}%", fill=TEXT, font=self._fonts["score"])
        self.create_text(cx, cy + 22, text=self._subtitle, fill=MUTED, font=self._fonts["tiny"])


class CapSlider(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.DoubleVar,
        *,
        from_: float = 25,
        to: float = 85,
        command=None,
    ) -> None:
        super().__init__(parent, height=28, bg=CARD, highlightthickness=0, bd=0, cursor="hand2")
        self.var = variable
        self.from_ = from_
        self.to = to
        self.command = command
        self._knob_r = 8
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Configure>", lambda _e: self._draw())
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _frac(self) -> float:
        try:
            v = float(self.var.get())
        except (tk.TclError, ValueError, TypeError):
            v = self.from_
        span = self.to - self.from_
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (v - self.from_) / span))

    def _draw(self) -> None:
        self.delete("all")
        w = int(self.winfo_width() or 200)
        h = int(self.winfo_height() or 28)
        y = h / 2
        x0, x1 = 10, w - 10
        self.create_line(x0, y, x1, y, fill=TRACK, width=6, capstyle="round")
        xf = x0 + (x1 - x0) * self._frac()
        self.create_line(x0, y, xf, y, fill=GOLD, width=6, capstyle="round")
        r = self._knob_r
        self.create_oval(xf - r, y - r, xf + r, y + r, fill=TEXT, outline=GOLD, width=2)

    def _drag(self, event) -> None:
        w = int(self.winfo_width() or 200)
        x0, x1 = 10, w - 10
        frac = 0.0 if x1 <= x0 else max(0.0, min(1.0, (event.x - x0) / (x1 - x0)))
        value = self.from_ + frac * (self.to - self.from_)
        self.var.set(value)
        if self.command:
            self.command(str(value))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"ZYTONA APP — HoN Net Guard — {qos.platform_name()}")
        # Size is fitted to content after UI build (see _fit_to_content).
        self.minsize(640, 480)
        self.configure(bg=BG)
        try:
            self.tk.call("tk", "scaling", 1.1)
        except tk.TclError:
            pass

        self.guard = HonNetGuard()
        self._closing = False
        self._status_job: str | None = None
        self._score_shown = 0.0
        self._score_target = 0.0
        self._score_job: str | None = None
        self._page = "guard"
        self._hog_rows: dict[str, int] = {}
        self._last_hog_warn = ""
        self._busy = False

        self._pick_fonts()
        self._build_style()
        self._build_ui()
        self.guard.monitor.on_update(self._on_snapshot)
        self.guard.start_monitor()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-q>", lambda _e: self._on_close())
        self.bind("<Control-Q>", lambda _e: self._on_close())
        self._status_job = self.after(400, self._refresh_status_bar)

    def _pick_fonts(self) -> None:
        if qos.is_windows():
            ui, mono = "Segoe UI", "Consolas"
        else:
            families = set()
            try:
                families = {str(f) for f in self.tk.call("font", "families")}
            except tk.TclError:
                pass
            ui = next(
                (n for n in ("Noto Sans", "DejaVu Sans", "Cantarell", "Sans") if n in families),
                "Sans",
            )
            mono = next(
                (n for n in ("JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono") if n in families),
                "Monospace",
            )
        self._ff = ui
        self._fm = mono
        self.fonts = {
            "title": (ui, 18, "bold"),
            "sub": (ui, 9),
            "section": (ui, 9, "bold"),
            "body": (ui, 10),
            "body_b": (ui, 10, "bold"),
            "btn": (ui, 10, "bold"),
            "tiny": (ui, 9),
            "metric": (ui, 15, "bold"),
            "score": (ui, 26, "bold"),
            "mono": (mono, 9),
            "stat": (mono, 10),
        }

    def _font(self, size: int = 10, bold: bool = False) -> tuple:
        return (self._ff, size, "bold") if bold else (self._ff, size)

    def _mono(self, size: int = 10) -> tuple:
        return (self._fm, size)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, font=self.fonts["body"])
        style.configure("TFrame", background=BG)
        style.configure(
            "Treeview",
            background=ENTRY,
            foreground=TEXT,
            fieldbackground=ENTRY,
            rowheight=28,
            font=self.fonts["body"],
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=CARD_HI,
            foreground=GOLD,
            font=self.fonts["body_b"],
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", "#2b3d55")],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=CARD_HI,
            troughcolor=ENTRY,
            bordercolor=CARD,
            arrowcolor=MUTED,
        )

    def _card(self, parent: tk.Misc, **pack) -> tk.Frame:
        wrap = tk.Frame(parent, bg=CARD, highlightbackground=EDGE, highlightthickness=1)
        if pack:
            wrap.pack(**pack)
        return wrap

    def _priv_text(self) -> tuple[str, str]:
        if qos.is_admin():
            return ("Root OK" if qos.is_linux() else "Admin OK", "ok")
        if qos.is_linux():
            return ("Need sudo", "warn")
        return ("Run as Admin", "warn")

    def _build_ui(self) -> None:
        # Dock first so it never gets pushed off-screen.
        dock = tk.Frame(self, bg=BG2, padx=18, pady=12)
        dock.pack(side="bottom", fill="x")
        tk.Frame(dock, bg=EDGE, height=1).pack(fill="x", pady=(0, 10))
        row = tk.Frame(dock, bg=BG2)
        row.pack(fill="x")
        self.btn_max = PillButton(
            row, "Max Ping 100%", self._activate_max, font=self.fonts["btn"], variant="primary", width=168
        )
        self.btn_max.pack(side="left", padx=(0, 8))
        self.btn_on = PillButton(
            row, "Enable", self._activate, font=self.fonts["btn"], width=110
        )
        self.btn_on.pack(side="left", padx=(0, 8))
        self.btn_kill = PillButton(
            row, "Kill Risky", self._kill_risky, font=self.fonts["btn"], variant="danger", width=120
        )
        self.btn_kill.pack(side="left", padx=(0, 8))
        self.btn_stop = PillButton(
            row, "Stop", self._deactivate, font=self.fonts["btn"], variant="danger", width=96
        )
        self.btn_stop.pack(side="left", padx=(0, 8))
        self.btn_save = PillButton(
            row, "Save", self._save_settings, font=self.fonts["btn"], variant="ghost", width=96
        )
        self.btn_save.pack(side="left")
        self.dock_hint = tk.StringVar(value="Ready")
        tk.Label(
            row, textvariable=self.dock_hint, bg=BG2, fg=MUTED, font=self.fonts["tiny"]
        ).pack(side="right")

        # Header
        header = tk.Frame(self, bg=BG, padx=20, pady=14)
        header.pack(side="top", fill="x")
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left")
        mark = tk.Canvas(brand, width=36, height=36, bg=BG, highlightthickness=0, bd=0)
        mark.pack(side="left", padx=(0, 10))
        _round_fill(mark, 2, 2, 34, 34, 8, GOLD)
        mark.create_text(18, 18, text="Z", fill=GOLD_FG, font=(self._ff, 14, "bold"))
        names = tk.Frame(brand, bg=BG)
        names.pack(side="left")
        tk.Label(names, text="ZYTONA APP", bg=BG, fg=TEXT, font=self.fonts["title"]).pack(
            anchor="w"
        )
        tk.Label(
            names, text="HoN Net Guard  ·  stabilize ping, stop timeouts", bg=BG, fg=MUTED, font=self.fonts["sub"]
        ).pack(anchor="w")

        chips = tk.Frame(header, bg=BG)
        chips.pack(side="right")
        self.chip_os = Chip(chips, self.fonts["tiny"])
        self.chip_os.pack(side="left", padx=4)
        self.chip_os.set(qos.platform_name(), "info")
        self.chip_priv = Chip(chips, self.fonts["tiny"])
        self.chip_priv.pack(side="left", padx=4)
        t, tone = self._priv_text()
        self.chip_priv.set(t, tone)
        self.chip_mode = Chip(chips, self.fonts["tiny"])
        self.chip_mode.pack(side="left", padx=4)
        self.chip_mode.set("Idle", "muted")

        # Tabs
        tabs = tk.Frame(self, bg=BG, padx=20)
        tabs.pack(side="top", fill="x", pady=(0, 8))
        self.tab_guard = TabChip(
            tabs, "Guard", lambda: self._show_page("guard"), self.fonts["body_b"], width=108
        )
        self.tab_guard.pack(side="left", padx=(0, 8))
        self.tab_live = TabChip(
            tabs, "HoN Live", lambda: self._show_page("live"), self.fonts["body_b"], width=120
        )
        self.tab_live.pack(side="left", padx=(0, 8))
        self.tab_hogs = TabChip(
            tabs, "Network Task Manager", lambda: self._show_page("hogs"), self.fonts["body_b"], width=210
        )
        self.tab_hogs.pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=20, pady=(0, 8))
        self._body = body

        self._page_guard = tk.Frame(body, bg=BG)
        self._page_live = tk.Frame(body, bg=BG)
        self._page_hogs = tk.Frame(body, bg=BG)
        self._build_guard(self._page_guard)
        self._build_live(self._page_live)
        self._build_hogs(self._page_hogs)
        self._show_page("guard")

        self._append_log("HoN Live tracks the game moment-by-moment when it opens.")
        if not qos.is_admin():
            self._append_log("Warning: without root/Admin the bandwidth cap cannot be applied.")

        # Default window size = content size (not a fixed oversized box).
        self.after_idle(self._fit_to_content)

    def _fit_to_content(self) -> None:
        """Resize the window to wrap the built UI, centered on screen."""
        try:
            self.update_idletasks()
            req_w = int(self.winfo_reqwidth())
            req_h = int(self.winfo_reqheight())
            # Small padding so nothing clips at the edges
            w = req_w + 16
            h = req_h + 16
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
            # Never exceed the screen; keep a usable minimum
            w = max(680, min(w, sw - 40))
            h = max(520, min(h, sh - 60))
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(min(680, w), min(520, h))
        except tk.TclError:
            pass

    def _show_page(self, name: str) -> None:
        self._page = name
        self._page_guard.pack_forget()
        self._page_live.pack_forget()
        self._page_hogs.pack_forget()
        pages = {
            "guard": self._page_guard,
            "live": self._page_live,
            "hogs": self._page_hogs,
        }
        pages.get(name, self._page_guard).pack(fill="both", expand=True)
        self.tab_guard.set_active(name == "guard")
        self.tab_live.set_active(name == "live")
        self.tab_hogs.set_active(name == "hogs")

    def _build_guard(self, tab: tk.Frame) -> None:
        top = tk.Frame(tab, bg=BG)
        top.pack(fill="x")

        score_wrap = self._card(top)
        score_wrap.pack(side="left", fill="y", padx=(0, 10))
        s_in = tk.Frame(score_wrap, bg=CARD)
        s_in.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(s_in, text="PING SCORE", bg=CARD, fg=GOLD, font=self.fonts["section"]).pack(
            anchor="w"
        )
        self.ring = ScoreRing(s_in, self.fonts)
        self.ring.pack(pady=(6, 4))
        self.score_detail = tk.StringVar(value="Enable Max Ping to stabilize the link")
        tk.Label(
            s_in,
            textvariable=self.score_detail,
            bg=CARD,
            fg=MUTED,
            font=self.fonts["tiny"],
            wraplength=180,
            justify="center",
        ).pack()

        tiles = tk.Frame(top, bg=BG)
        tiles.pack(side="left", fill="both", expand=True)
        tiles.columnconfigure(0, weight=1)
        tiles.columnconfigure(1, weight=1)
        tiles.rowconfigure(0, weight=1)
        tiles.rowconfigure(1, weight=1)

        self.tile_game = MetricTile(tiles, "Game", self.fonts)
        self.tile_ping = MetricTile(tiles, "Ping", self.fonts)
        self.tile_down = MetricTile(tiles, "Download", self.fonts)
        self.tile_up = MetricTile(tiles, "Upload", self.fonts)
        self.tile_game.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        self.tile_ping.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        self.tile_down.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(6, 0))
        self.tile_up.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(6, 0))
        self.tile_game.set("Not detected", "Launch HoN Reborn", "warn")
        self.tile_ping.set("—", self.guard.settings.ping_host)
        self.tile_down.set("—", "live")
        self.tile_up.set("—", "live")

        self.warn_wrap = tk.Frame(tab, bg="#2a1814", highlightbackground="#5a3028", highlightthickness=1)
        self.warn_var = tk.StringVar(value="")
        tk.Label(
            self.warn_wrap,
            textvariable=self.warn_var,
            bg="#2a1814",
            fg=ORANGE,
            font=self.fonts["body_b"],
            wraplength=860,
            justify="left",
            padx=12,
            pady=8,
        ).pack(fill="x")

        settings = self._card(tab, fill="x", pady=(10, 0))
        self._settings_card = settings
        inner = tk.Frame(settings, bg=CARD)
        inner.pack(fill="x", padx=16, pady=14)
        tk.Label(inner, text="SETTINGS", bg=CARD, fg=GOLD, font=self.fonts["section"]).pack(
            anchor="w", pady=(0, 10)
        )

        self.link_var = tk.DoubleVar(value=self.guard.settings.link_mbps)
        share = MAX_PING_SHARE if self.guard.settings.max_ping_mode else self.guard.settings.game_share
        self.share_var = tk.DoubleVar(value=share * 100)
        self.throttle_label = tk.StringVar()
        self.max_ping_var = tk.BooleanVar(value=self.guard.settings.max_ping_mode)
        self.do_var = tk.BooleanVar(value=self.guard.settings.tame_delivery_optimization)
        self.dscp_var = tk.BooleanVar(value=self.guard.settings.mark_dscp)
        self.share_value = tk.StringVar(value=f"{int(self.share_var.get())}%")

        grid = tk.Frame(inner, bg=CARD)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        tk.Label(grid, text="Your download speed", bg=CARD, fg=TEXT, font=self.fonts["body"]).grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        speed = tk.Frame(grid, bg=CARD)
        speed.grid(row=0, column=1, sticky="e")
        self.speed_entry = tk.Entry(
            speed,
            textvariable=self.link_var,
            width=8,
            justify="center",
            bg=ENTRY,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=self.fonts["body_b"],
            highlightthickness=1,
            highlightbackground=EDGE,
            highlightcolor=GOLD,
        )
        self.speed_entry.pack(side="left")
        tk.Label(speed, text="  Mbps", bg=CARD, fg=MUTED, font=self.fonts["body"]).pack(side="left")

        tk.Label(grid, text="Bandwidth cap share", bg=CARD, fg=TEXT, font=self.fonts["body"]).grid(
            row=1, column=0, sticky="w", pady=(14, 0)
        )
        tk.Label(grid, textvariable=self.share_value, bg=CARD, fg=GOLD, font=self.fonts["body_b"]).grid(
            row=1, column=1, sticky="e", pady=(14, 0)
        )

        self.slider = CapSlider(inner, self.share_var, command=self._on_share_move)
        self.slider.pack(fill="x", pady=(8, 6))

        tk.Label(
            inner, textvariable=self.throttle_label, bg=CARD, fg=CYAN, font=self.fonts["stat"]
        ).pack(anchor="w", pady=(2, 8))

        self._make_check(
            inner,
            "Max ping mode  —  more headroom + system latency tweaks",
            self.max_ping_var,
            self._on_max_toggle,
        )
        if qos.is_windows():
            self._make_check(
                inner,
                "Disable Windows Update Delivery Optimization",
                self.do_var,
                None,
            )

        self.link_var.trace_add("write", lambda *_: self._update_throttle_label())
        self._update_throttle_label()

        log_head = tk.Frame(tab, bg=BG)
        log_head.pack(fill="x", pady=(10, 4))
        tk.Label(log_head, text="ACTIVITY", bg=BG, fg=MUTED, font=self.fonts["section"]).pack(
            anchor="w"
        )
        log_wrap = tk.Frame(tab, bg=ENTRY, highlightbackground=EDGE, highlightthickness=1)
        log_wrap.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_wrap,
            height=6,
            bg=ENTRY,
            fg="#c5d0dc",
            insertbackground=TEXT,
            font=self.fonts["mono"],
            relief="flat",
            wrap="word",
            padx=12,
            pady=10,
            highlightthickness=0,
            borderwidth=0,
            state="normal",
        )
        scroll = ttk.Scrollbar(log_wrap, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Unused StringVars kept so older snapshot code paths stay simple
        self.game_var = tk.StringVar()
        self.down_var = tk.StringVar()
        self.up_var = tk.StringVar()
        self.ping_var = tk.StringVar()

    def _make_check(self, parent: tk.Misc, text: str, var: tk.BooleanVar, command) -> None:
        tk.Checkbutton(
            parent,
            text=text,
            variable=var,
            command=command,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=GOLD,
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=self.fonts["body"],
            anchor="w",
            padx=0,
        ).pack(anchor="w", pady=2)

    def _build_live(self, tab: tk.Frame) -> None:
        card = self._card(tab, fill="both", expand=True)
        wrap = tk.Frame(card, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=16, pady=14)

        head = tk.Frame(wrap, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text="HON LIVE TRACKER", bg=CARD, fg=GOLD, font=self.fonts["section"]).pack(
            side="left"
        )
        self.live_clock = tk.StringVar(value="--:--:--")
        tk.Label(head, textvariable=self.live_clock, bg=CARD, fg=CYAN, font=self.fonts["stat"]).pack(
            side="right"
        )

        # Big ping panel
        ping_box = tk.Frame(wrap, bg=CARD_HI, highlightbackground=EDGE, highlightthickness=1)
        ping_box.pack(fill="x", pady=(12, 8))
        ping_in = tk.Frame(ping_box, bg=CARD_HI)
        ping_in.pack(fill="x", padx=14, pady=12)
        tk.Label(ping_in, text="LIVE PING", bg=CARD_HI, fg=GOLD, font=self.fonts["section"]).pack(
            anchor="w"
        )
        self.live_ping_big = tk.StringVar(value="— ms")
        self.live_ping_label = tk.Label(
            ping_in, textvariable=self.live_ping_big, bg=CARD_HI, fg=GREEN, font=self.fonts["score"]
        )
        self.live_ping_label.pack(anchor="w", pady=(4, 0))
        self.live_ping_detail = tk.StringVar(value="Waiting for samples...")
        tk.Label(
            ping_in, textvariable=self.live_ping_detail, bg=CARD_HI, fg=MUTED, font=self.fonts["tiny"]
        ).pack(anchor="w", pady=(2, 0))
        self.live_ping_hist = tk.StringVar(value="History: —")
        tk.Label(
            ping_in, textvariable=self.live_ping_hist, bg=CARD_HI, fg=MUTED, font=self.fonts["mono"]
        ).pack(anchor="w", pady=(4, 0))

        self.live_status = tk.StringVar(value="Waiting for HoN / juvio.exe ...")
        tk.Label(
            wrap, textvariable=self.live_status, bg=CARD, fg=TEXT, font=self.fonts["body_b"]
        ).pack(anchor="w", pady=(6, 4))

        metrics = tk.Frame(wrap, bg=CARD)
        metrics.pack(fill="x", pady=(2, 8))
        self.live_session = tk.StringVar(value="Session: 00:00")
        self.live_cpu = tk.StringVar(value="CPU: —")
        self.live_ram = tk.StringVar(value="RAM: —")
        self.live_net = tk.StringVar(value="Sockets: —")
        self.live_bw = tk.StringVar(value="Link: —")
        self.live_hogs = tk.StringVar(value="HoN net hogs: 0")
        for var in (
            self.live_session,
            self.live_cpu,
            self.live_ram,
            self.live_net,
            self.live_bw,
            self.live_hogs,
        ):
            tk.Label(metrics, textvariable=var, bg=CARD, fg=MUTED, font=self.fonts["stat"]).pack(
                anchor="w", pady=1
            )

        # Action buttons for HoN services
        acts = tk.Frame(wrap, bg=CARD)
        acts.pack(fill="x", pady=(4, 8))
        PillButton(
            acts, "Fix HoN Net", self._fix_hon_net, font=self.fonts["btn"], variant="primary", width=140
        ).pack(side="left", padx=(0, 8))
        PillButton(
            acts, "Stop Selected", self._stop_hon_selected, font=self.fonts["btn"], variant="danger", width=140
        ).pack(side="left", padx=(0, 8))
        PillButton(
            acts, "Stop All Hogs", self._stop_hon_hogs, font=self.fonts["btn"], variant="danger", width=140
        ).pack(side="left")

        tk.Label(
            wrap,
            text="HoN SERVICES / PROCESSES  (red = net hog — can stop)",
            bg=CARD,
            fg=GOLD,
            font=self.fonts["section"],
        ).pack(anchor="w", pady=(8, 4))
        tree_frame = tk.Frame(wrap, bg=CARD)
        tree_frame.pack(fill="both", expand=True)
        cols = ("name", "pid", "role", "activity", "conns", "hog", "reason")
        self.live_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="browse", height=7
        )
        for key, title, width in (
            ("name", "Process", 130),
            ("pid", "PID", 60),
            ("role", "Role", 90),
            ("activity", "Net Activity", 100),
            ("conns", "Conns", 70),
            ("hog", "Hog?", 60),
            ("reason", "Notes", 260),
        ):
            self.live_tree.heading(key, text=title)
            self.live_tree.column(key, width=width, anchor="w")
        self.live_tree.tag_configure("hog", foreground=ORANGE)
        self.live_tree.tag_configure("core", foreground=GREEN)
        self.live_tree.tag_configure("service", foreground=RED)
        self.live_tree.tag_configure("ok", foreground=MUTED)
        live_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.live_tree.yview)
        self.live_tree.configure(yscrollcommand=live_scroll.set)
        self.live_tree.pack(side="left", fill="both", expand=True)
        live_scroll.pack(side="right", fill="y")
        self._live_rows: dict[str, int] = {}

        tk.Label(wrap, text="REMOTE ENDPOINTS", bg=CARD, fg=GOLD, font=self.fonts["section"]).pack(
            anchor="w", pady=(10, 4)
        )
        self.live_remotes = tk.StringVar(value="No remote connections yet")
        tk.Label(
            wrap,
            textvariable=self.live_remotes,
            bg=CARD,
            fg=MUTED,
            font=self.fonts["tiny"],
            wraplength=820,
            justify="left",
        ).pack(anchor="w")

        tk.Label(wrap, text="EVENT LOG", bg=CARD, fg=GOLD, font=self.fonts["section"]).pack(
            anchor="w", pady=(10, 4)
        )
        self.live_events = tk.Text(
            wrap,
            height=4,
            bg=ENTRY,
            fg="#c5d0dc",
            font=self.fonts["mono"],
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=EDGE,
        )
        self.live_events.pack(fill="x")
        self._live_was_running = False
        self._last_hon_state = None

    def _build_hogs(self, tab: tk.Frame) -> None:
        card = self._card(tab, fill="both", expand=True)
        h_in = tk.Frame(card, bg=CARD)
        h_in.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(h_in, text="WHO IS EATING YOUR INTERNET", bg=CARD, fg=GOLD, font=self.fonts["section"]).pack(
            anchor="w"
        )
        tk.Label(
            h_in,
            text="Task Manager for the network — high-risk apps often cause HoN timeouts",
            bg=CARD,
            fg=MUTED,
            font=self.fonts["tiny"],
        ).pack(anchor="w", pady=(2, 8))
        self.hogs_summary = tk.StringVar(value="Scanning network processes...")
        tk.Label(h_in, textvariable=self.hogs_summary, bg=CARD, fg=CYAN, font=self.fonts["stat"]).pack(
            anchor="w", pady=(0, 8)
        )

        tree_frame = tk.Frame(h_in, bg=CARD)
        tree_frame.pack(fill="both", expand=True)
        cols = ("process", "pid", "conns", "activity", "risk", "reason")
        self.hog_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse", height=14)
        headings = {
            "process": ("Process", 150),
            "pid": ("PID", 70),
            "conns": ("Connections", 100),
            "activity": ("Activity", 100),
            "risk": ("Risk", 80),
            "reason": ("Why it hurts ping", 280),
        }
        for key, (title, width) in headings.items():
            self.hog_tree.heading(key, text=title)
            self.hog_tree.column(key, width=width, anchor="w")
        self.hog_tree.tag_configure("high", foreground=ORANGE)
        self.hog_tree.tag_configure("game", foreground=GREEN)
        self.hog_tree.tag_configure("medium", foreground=GOLD)
        self.hog_tree.tag_configure("low", foreground=MUTED)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.hog_tree.yview)
        self.hog_tree.configure(yscrollcommand=tree_scroll.set)
        self.hog_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        hog_btns = tk.Frame(h_in, bg=CARD)
        hog_btns.pack(fill="x", pady=(12, 0))
        PillButton(hog_btns, "Refresh Scan", self._manual_hog_scan, font=self.fonts["btn"], width=140).pack(
            side="left", padx=(0, 8)
        )
        PillButton(
            hog_btns, "Kill Selected", self._kill_selected, font=self.fonts["btn"], variant="danger", width=140
        ).pack(side="left", padx=(0, 8))
        PillButton(
            hog_btns, "Kill All High-Risk", self._kill_risky, font=self.fonts["btn"], variant="danger", width=168
        ).pack(side="left")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_max.set_enabled(not busy)
        self.btn_on.set_enabled(not busy)
        if busy:
            self.btn_max.set_text("Measuring...")
            self.dock_hint.set("Measuring ping — please wait")
        else:
            self.btn_max.set_text("Max Ping 100%")

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
            f"Expected cap  ~ {tmp.throttle_mbps():.1f} Mbps     Headroom  ~ {link - tmp.throttle_mbps():.1f} Mbps"
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
        if self._closing or self._busy:
            return
        self._read_settings_into_guard()
        if max_ping:
            self.max_ping_var.set(True)
            self.share_var.set(MAX_PING_SHARE * 100)
            self.share_value.set(f"{int(MAX_PING_SHARE * 100)}%")
            self._read_settings_into_guard()
        self._set_busy(True)
        self._append_log("Activating and measuring ping (a few seconds)...")
        self.update_idletasks()

        def worker() -> None:
            ok = self.guard.activate(max_ping=max_ping)
            if self._closing:
                return
            self.after(0, lambda: self._finish_activate(ok))

        threading.Thread(target=worker, name="hon-activate", daemon=True).start()

    def _finish_activate(self, ok: bool) -> None:
        if self._closing:
            return
        self._set_busy(False)
        for line in self.guard.status.history[-10:]:
            self._append_log(line)
        self._set_score(self.guard.status.live_score)
        self._sync_mode_chip()
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
        self._sync_mode_chip()

    def _sync_mode_chip(self) -> None:
        st = self.guard.status
        if st.active and st.max_ping_mode:
            self.chip_mode.set("Max Ping", "gold")
        elif st.active:
            self.chip_mode.set("Active", "ok")
        else:
            self.chip_mode.set("Idle", "muted")

    def _set_score(self, value: float) -> None:
        value = max(0.0, min(100.0, value))
        self._score_target = value
        if value >= 100:
            self.score_detail.set("Fully stable — no saturation, steady ping")
        elif value >= 70:
            self.score_detail.set("Strong improvement — keep the game open")
        elif value > 0:
            self.score_detail.set("Guard active — waiting for samples")
        else:
            self.score_detail.set("Inactive")
        if self._score_job is None and not self._closing:
            self._tick_score()

    def _tick_score(self) -> None:
        if self._closing:
            self._score_job = None
            return
        cur = self._score_shown
        tgt = self._score_target
        if abs(cur - tgt) < 0.4:
            self._score_shown = tgt
            self.ring.set(tgt, "STABLE" if tgt >= 100 else ("LIVE" if tgt > 0 else "IDLE"))
            self._score_job = None
            return
        self._score_shown = cur + (tgt - cur) * 0.28
        self.ring.set(self._score_shown, "STABLE" if tgt >= 100 else ("LIVE" if tgt > 0 else "IDLE"))
        self._score_job = self.after(16, self._tick_score)

    def _set_warn(self, text: str) -> None:
        self.warn_var.set(text)
        try:
            mapped = bool(self.warn_wrap.winfo_ismapped())
        except tk.TclError:
            return
        if text and not mapped:
            self.warn_wrap.pack(fill="x", pady=(10, 0), before=self._settings_card)
        elif not text and mapped:
            self.warn_wrap.pack_forget()

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")
        short = text if len(text) < 48 else text[:45] + "..."
        self.dock_hint.set(short)

    def _on_snapshot(self, snap: Snapshot) -> None:
        if self._closing:
            return
        try:
            self.after(0, lambda s=snap: self._apply_snapshot(s))
        except tk.TclError:
            return

    def _apply_snapshot(self, snap: Snapshot) -> None:
        if self._closing:
            return
        try:
            if snap.game_found:
                names = ", ".join(sorted({p.name for p in snap.processes}))
                self.tile_game.set("Running", names or "HoN Reborn", "good")
                self.game_var.set(f"Game: running ({names})")
            else:
                self.tile_game.set("Not detected", "Launch HoN Reborn", "warn")
                self.game_var.set("Game: not detected — launch HoN Reborn")

            self.tile_down.set(format_rate(snap.total_down_bps), "live")
            self.tile_up.set(format_rate(snap.total_up_bps), "live")
            self.down_var.set(f"Download: {format_rate(snap.total_down_bps)}")
            self.up_var.set(f"Upload: {format_rate(snap.total_up_bps)}")

            host = self.guard.settings.ping_host
            if snap.ping_ok and snap.ping_ms is not None:
                tone = "good" if snap.ping_ms < 80 else ("warn" if snap.ping_ms < 140 else "bad")
                self.tile_ping.set(f"{snap.ping_ms:.0f} ms", host, tone)
                self.ping_var.set(f"Ping ({host}): {snap.ping_ms:.0f} ms")
            elif snap.ping_ok:
                self.tile_ping.set("OK", host, "good")
                self.ping_var.set(f"Ping ({host}): OK")
            else:
                self.tile_ping.set("Timeout", host, "bad")
                self.ping_var.set(f"Ping ({host}): timeout / failed")

            if snap.saturating:
                self._set_warn("Link saturated — lower share % or enable Max Ping mode")
            elif not snap.ping_ok and snap.game_found:
                self._set_warn("Timeout detected — enable Max Ping 100%")
            else:
                self._set_warn("")

            score = self.guard.update_live_score(snap)
            self._set_score(score)
            self._update_hog_table(snap)
            self._update_hon_live(snap)
            self.guard.reapply_if_needed(snap)
            self._sync_mode_chip()
        except tk.TclError:
            return

    def _live_event(self, text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}\n"
        try:
            self.live_events.insert("end", line)
            self.live_events.see("end")
        except tk.TclError:
            pass
        self._append_log(text)

    def _update_hon_live(self, snap: Snapshot) -> None:
        hon = getattr(snap, "hon", None)
        if hon is None:
            return
        self._last_hon_state = hon
        self.live_clock.set(hon.clock or time.strftime("%H:%M:%S"))

        # Big ping display
        if snap.ping_ok and snap.ping_ms is not None:
            self.live_ping_big.set(f"{snap.ping_ms:.0f} ms")
            if snap.ping_ms < 70:
                color = GREEN
                tone = "Excellent"
            elif snap.ping_ms < 120:
                color = GOLD
                tone = "Playable"
            else:
                color = ORANGE
                tone = "High — check HoN net hogs"
            self.live_ping_label.configure(fg=color)
            self.live_ping_detail.set(
                f"{tone}  ·  target {self.guard.settings.ping_host}  ·  live while HoN runs"
            )
        elif snap.ping_ok:
            self.live_ping_big.set("OK")
            self.live_ping_label.configure(fg=GREEN)
            self.live_ping_detail.set("Reply OK (no timing)")
        else:
            self.live_ping_big.set("TIMEOUT")
            self.live_ping_label.configure(fg=RED)
            self.live_ping_detail.set("Ping failed — enable Max Ping / Fix HoN Net")

        hist = hon.ping_history or []
        if hist:
            self.live_ping_hist.set(
                "History: " + " → ".join(f"{v:.0f}" for v in hist[-12:]) + " ms"
            )
        else:
            self.live_ping_hist.set("History: collecting...")

        if hon.just_opened:
            self._live_event(
                f"HoN OPENED — {hon.primary_name or 'game'} PID {hon.primary_pid} "
                f"({hon.process_count} process(es))"
            )
            self._live_was_running = True
        if hon.just_closed:
            self._live_event("HoN CLOSED — session ended")
            self._live_was_running = False

        if hon.running:
            self.live_status.set(
                f"TRACKING  ·  {hon.primary_name or 'HoN'}  ·  PID {hon.primary_pid}  ·  "
                f"{hon.process_count} process(es)"
            )
            self.live_session.set(f"Session: {format_duration(hon.session_seconds)}")
            self.live_cpu.set(f"CPU: {hon.cpu_pct:.1f}%")
            self.live_ram.set(f"RAM: {hon.ram_mb:.0f} MB")
            self.live_net.set(f"Sockets: {hon.established} established / {hon.connections} total")
            self.live_bw.set(
                f"Link: ↓ {format_rate(snap.total_down_bps)}   ↑ {format_rate(snap.total_up_bps)}"
            )
            self.live_hogs.set(
                f"HoN net hogs: {hon.hog_count}  ·  stoppable: {len(hon.stoppable)}"
            )
            if hon.hog_count and snap.saturating:
                self._set_warn(
                    f"HoN service hogging net — use Fix HoN Net ({hon.hog_count} flagged)"
                )
            if hon.remotes:
                self.live_remotes.set("  ·  ".join(hon.remotes))
            else:
                self.live_remotes.set("Connected locally / no remote endpoints yet")
        else:
            self.live_status.set("Waiting for HoN / juvio.exe ...")
            self.live_session.set("Session: 00:00")
            self.live_cpu.set("CPU: —")
            self.live_ram.set("RAM: —")
            self.live_net.set("Sockets: —")
            self.live_bw.set("Link: —")
            self.live_hogs.set("HoN net hogs: 0")
            self.live_remotes.set("No remote connections yet")

        selected_pid = None
        sel = self.live_tree.selection()
        if sel:
            selected_pid = self._live_rows.get(sel[0])

        self.live_tree.delete(*self.live_tree.get_children())
        self._live_rows.clear()
        reselect = None
        for p in hon.processes:
            tag = "core" if p.role == "core" else ("hog" if p.net_hog else ("service" if p.role == "service" else "ok"))
            iid = self.live_tree.insert(
                "",
                "end",
                values=(
                    p.name,
                    p.pid,
                    p.role.upper(),
                    hon_format_activity(p.activity_bps),
                    f"{p.established}/{p.connections}",
                    "YES" if p.net_hog else "no",
                    p.reason,
                ),
                tags=(tag,),
            )
            self._live_rows[iid] = p.pid
            if selected_pid == p.pid:
                reselect = iid
        if reselect:
            self.live_tree.selection_set(reselect)

    def _stop_hon_selected(self) -> None:
        sel = self.live_tree.selection()
        if not sel:
            messagebox.showinfo("Stop Selected", "Select a HoN service/process first.")
            return
        pid = self._live_rows.get(sel[0])
        if not pid:
            return
        if not messagebox.askyesno("Confirm", f"Stop HoN-related PID {pid}?\n(Core game is protected)"):
            return
        ok, msg = stop_hon_service(pid)
        self._live_event(msg)
        if not ok:
            messagebox.showwarning("Stop", msg)

    def _stop_hon_hogs(self) -> None:
        state = self._last_hon_state
        if state is None or not state.stoppable:
            messagebox.showinfo("Stop All Hogs", "No stoppable HoN net hogs right now.")
            return
        names = ", ".join(f"{p.name}({p.pid})" for p in state.stoppable[:8])
        if not messagebox.askyesno("Confirm", f"Stop these HoN net hogs?\n\n{names}"):
            return
        for msg in fix_hon_net_hogs(state):
            self._live_event(msg)

    def _fix_hon_net(self) -> None:
        """Stop HoN net-hog services + re-apply bandwidth guard."""
        self._live_event("Fix HoN Net: scanning & stopping hogs...")
        state = self._last_hon_state
        if state is not None:
            for msg in fix_hon_net_hogs(state):
                self._live_event(msg)
        # Re-apply shaping without full ping round if already active, else activate max
        if self.guard.status.active:
            result = qos.apply_throttle(self.guard.settings)
            if result.ok:
                self._live_event("Bandwidth cap re-applied.")
            else:
                self._live_event(f"Cap re-apply failed: {result.stderr or result.stdout}")
        else:
            self._live_event("Guard was off — enabling Max Ping mode...")
            self._activate_max()
        flush = qos.flush_dns()
        if flush.ok and flush.stdout != "skip":
            self._live_event("DNS flushed.")
        self._live_event("Fix HoN Net done.")

    def _update_hog_table(self, snap: Snapshot) -> None:
        hogs = getattr(snap, "hogs", []) or []
        high = sum(1 for h in hogs if getattr(h, "risk", "") == "high")
        self.hogs_summary.set(
            f"Tracked sockets: {snap.hog_connections}   ·   Listed: {len(hogs)}   ·   High-risk: {high}"
        )

        selected_pid = None
        sel = self.hog_tree.selection()
        if sel:
            selected_pid = self._hog_rows.get(sel[0])

        self.hog_tree.delete(*self.hog_tree.get_children())
        self._hog_rows.clear()
        reselect = None
        for hog in hogs:
            iid = self.hog_tree.insert(
                "",
                "end",
                values=(
                    hog.name,
                    hog.pid,
                    f"{hog.established}/{hog.connections}",
                    format_activity(hog.activity),
                    hog.risk.upper(),
                    hog.reason,
                ),
                tags=(hog.risk,),
            )
            self._hog_rows[iid] = hog.pid
            if selected_pid == hog.pid:
                reselect = iid
        if reselect:
            self.hog_tree.selection_set(reselect)

        if snap.saturating and high:
            top = next((h for h in hogs if h.risk == "high"), None)
            msg = (
                f"Saturation + high-risk app: {top.name} (PID {top.pid}) — kill it to stop timeouts"
                if top
                else "Link saturated — open Network Task Manager and kill high-risk apps"
            )
            if msg != self._last_hog_warn:
                self._last_hog_warn = msg
                self._set_warn(msg)
                self._append_log(msg)

    def _manual_hog_scan(self) -> None:
        if self._closing:
            return
        try:
            scan = self.guard.monitor._hog_scanner.scan(top_n=12)
            self.guard.monitor._last_hogs = scan.hogs
            self.guard.monitor._last_hog_conns = scan.total_connections
            fake = Snapshot(
                timestamp=scan.timestamp,
                game_found=False,
                hogs=scan.hogs,
                hog_connections=scan.total_connections,
            )
            self._update_hog_table(fake)
            self._append_log(f"Manual scan: {len(scan.hogs)} network processes listed.")
        except Exception as exc:
            self._append_log(f"Scan failed: {exc}")

    def _kill_selected(self) -> None:
        sel = self.hog_tree.selection()
        if not sel:
            messagebox.showinfo("Kill Selected", "Select a process in the list first.")
            return
        pid = self._hog_rows.get(sel[0])
        if not pid:
            return
        if not messagebox.askyesno("Confirm", f"Kill PID {pid}?"):
            return
        ok, msg = kill_process(pid)
        self._append_log(msg)
        if ok:
            self._manual_hog_scan()

    def _kill_risky(self) -> None:
        hogs = list(getattr(self.guard.monitor, "_last_hogs", []) or [])
        if not hogs:
            self._manual_hog_scan()
            hogs = list(getattr(self.guard.monitor, "_last_hogs", []) or [])
        risky = [h for h in hogs if h.risk == "high" and h.can_kill]
        if not risky:
            messagebox.showinfo("Kill Risky", "No high-risk bandwidth hogs found right now.")
            return
        names = ", ".join(f"{h.name}({h.pid})" for h in risky[:8])
        if not messagebox.askyesno(
            "Confirm",
            f"Kill these high-risk apps?\n\n{names}\n\n(Game process will NOT be killed)",
        ):
            return
        for msg in kill_high_risk(risky):
            self._append_log(msg)
        self._manual_hog_scan()

    def _refresh_status_bar(self) -> None:
        if self._closing:
            return
        try:
            t, tone = self._priv_text()
            self.chip_priv.set(t, tone)
            self._sync_mode_chip()
            self._status_job = self.after(2000, self._refresh_status_bar)
        except tk.TclError:
            self._status_job = None

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            if self._status_job is not None:
                try:
                    self.after_cancel(self._status_job)
                except (tk.TclError, ValueError):
                    pass
                self._status_job = None
            if self._score_job is not None:
                try:
                    self.after_cancel(self._score_job)
                except (tk.TclError, ValueError):
                    pass
                self._score_job = None
            try:
                self._append_log("Shutting down...")
                self.update_idletasks()
            except tk.TclError:
                pass
            self.guard.shutdown(remove_qos=True)
        except Exception:
            try:
                self.guard.shutdown(remove_qos=True)
            except Exception:
                pass
        try:
            self.quit()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


def run_gui() -> None:
    app = App()
    try:
        app.mainloop()
    finally:
        if not getattr(app, "_closing", False):
            try:
                app.guard.shutdown(remove_qos=True)
            except Exception:
                pass
