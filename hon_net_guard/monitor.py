"""Process + network monitoring for HoN and overall link health."""

from __future__ import annotations

import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import psutil

from .config import CMDLINE_MARKERS, Settings
from .hogs import NetworkHogScanner
from .hon_tracker import HonLiveState, HonLiveTracker

_PING_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)


@dataclass
class ProcessNetStats:
    name: str
    pid: int
    down_bps: float = 0.0
    up_bps: float = 0.0


@dataclass
class Snapshot:
    timestamp: float
    game_found: bool
    processes: list[ProcessNetStats] = field(default_factory=list)
    total_down_bps: float = 0.0
    total_up_bps: float = 0.0
    game_down_bps: float = 0.0
    game_up_bps: float = 0.0
    ping_ms: float | None = None
    ping_ok: bool = False
    saturating: bool = False
    hogs: list = field(default_factory=list)
    hog_connections: int = 0
    hon: HonLiveState | None = None


def ping_once(
    host: str,
    timeout_sec: float = 0.9,
    stop_event: threading.Event | None = None,
) -> tuple[bool, float | None]:
    """Single ping that can be aborted via stop_event."""
    if stop_event is not None and stop_event.is_set():
        return False, None

    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(max(1, int(timeout_sec * 1000))), host]
    else:
        # -W is seconds on Linux (integer on many distros)
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout_sec))), host]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False, None

    deadline = time.time() + timeout_sec + 0.4
    try:
        while proc.poll() is None:
            if stop_event is not None and stop_event.is_set():
                _kill(proc)
                return False, None
            if time.time() >= deadline:
                _kill(proc)
                return False, None
            time.sleep(0.05)

        out = (proc.stdout.read() if proc.stdout else "") + (
            proc.stderr.read() if proc.stderr else ""
        )
        if proc.returncode != 0:
            return False, None
        match = _PING_RE.search(out)
        if match:
            return True, float(match.group(1))
        return True, None
    except Exception:
        _kill(proc)
        return False, None


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=0.3)
    except Exception:
        pass


# Back-compat alias
_ping_once = ping_once


def _looks_like_game(name: str, cmdline: str, names: set[str]) -> bool:
    if name in names:
        return True
    blob = f"{name} {cmdline}".lower()
    return any(marker in blob for marker in CMDLINE_MARKERS)


class NetMonitor:
    def __init__(self, settings: Settings, interval: float = 1.0) -> None:
        self.settings = settings
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable[[Snapshot], None]] = []
        self._prev_io: dict[int, tuple[int, int, float]] = {}
        self._prev_nic: tuple[int, int, float] | None = None
        self.latest: Snapshot | None = None
        self._tick = 0
        self._last_ping_ok = False
        self._last_ping_ms: float | None = None
        self._lock = threading.Lock()
        self._hog_scanner = NetworkHogScanner()
        self._last_hogs: list = []
        self._last_hog_conns = 0
        self._hon_tracker = HonLiveTracker()
        self._game_interval = 0.5
        self._idle_interval = max(interval, 1.0)

    def on_update(self, callback: Callable[[Snapshot], None]) -> None:
        self._callbacks.append(callback)

    def clear_callbacks(self) -> None:
        self._callbacks.clear()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="hon-net-monitor", daemon=True
            )
            self._thread.start()

    def stop(self, join_timeout: float = 1.0) -> None:
        """Signal stop and wait briefly. Never blocks the UI for long."""
        self._stop.set()
        thread = None
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _target_names(self) -> set[str]:
        return {n.strip().lower() for n in self.settings.process_names if n.strip()}

    def _sample(self) -> Snapshot | None:
        if self._stop.is_set():
            return None

        now = time.time()
        names = self._target_names()
        procs: list[ProcessNetStats] = []

        # Fast path: name-only first; cmdline only for wine-like hosts.
        wine_hosts = {"wine", "wine64", "wine-preloader", "wine64-preloader", "wineserver"}
        for proc in psutil.process_iter(["pid", "name"]):
            if self._stop.is_set():
                return None
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = ""
                if name not in names:
                    if name in wine_hosts or name.endswith(".exe"):
                        try:
                            cmdline = " ".join(proc.cmdline()).lower()
                        except (psutil.Error, OSError):
                            cmdline = ""
                    if not _looks_like_game(name, cmdline, names):
                        continue
                io = proc.io_counters()
                read_b = int(getattr(io, "read_bytes", 0) or 0)
                write_b = int(getattr(io, "write_bytes", 0) or 0)
                prev = self._prev_io.get(proc.pid)
                down_bps = up_bps = 0.0
                if prev:
                    dt = max(now - prev[2], 0.001)
                    down_bps = max(0.0, (read_b - prev[0]) / dt)
                    up_bps = max(0.0, (write_b - prev[1]) / dt)
                self._prev_io[proc.pid] = (read_b, write_b, now)
                procs.append(
                    ProcessNetStats(name=name, pid=proc.pid, down_bps=down_bps, up_bps=up_bps)
                )
            except (psutil.Error, OSError):
                continue

        nic = psutil.net_io_counters()
        total_down = total_up = 0.0
        if self._prev_nic:
            dt = max(now - self._prev_nic[2], 0.001)
            total_down = max(0.0, (nic.bytes_recv - self._prev_nic[0]) / dt)
            total_up = max(0.0, (nic.bytes_sent - self._prev_nic[1]) / dt)
        self._prev_nic = (nic.bytes_recv, nic.bytes_sent, now)

        # Live HoN tracker — every tick
        hon_state = self._hon_tracker.sample()

        # When HoN is open: ping every tick for moment-by-moment latency.
        self._tick += 1
        ping_every = 1 if hon_state.running else 2
        if self._tick % ping_every == 0 and not self._stop.is_set():
            ok, ms = ping_once(self.settings.ping_host, timeout_sec=0.7, stop_event=self._stop)
            self._last_ping_ok = ok
            self._last_ping_ms = ms
            self._hon_tracker.note_ping(ok, ms)

        hon_state.ping_ok = self._last_ping_ok
        hon_state.ping_ms = self._last_ping_ms
        hon_state.ping_history = self._hon_tracker.ping_history()

        game_found = hon_state.running or bool(procs)
        game_down = total_down if game_found else 0.0
        game_up = total_up if game_found else 0.0

        link_bps = max(self.settings.link_mbps * 1_000_000 / 8.0, 1.0)
        saturating = total_down >= link_bps * 0.85 or total_up >= link_bps * 0.85

        # Network Task Manager scan less often while gaming (keep loop snappy).
        hog_every = 4 if hon_state.running else 3
        if self._tick % hog_every == 0 and not self._stop.is_set():
            try:
                scan = self._hog_scanner.scan(top_n=12)
                self._last_hogs = scan.hogs
                self._last_hog_conns = scan.total_connections
            except Exception:
                pass

        snap = Snapshot(
            timestamp=now,
            game_found=game_found,
            processes=procs,
            total_down_bps=total_down,
            total_up_bps=total_up,
            game_down_bps=game_down,
            game_up_bps=game_up,
            ping_ms=self._last_ping_ms,
            ping_ok=self._last_ping_ok,
            saturating=saturating,
            hogs=list(self._last_hogs),
            hog_connections=self._last_hog_conns,
            hon=hon_state,
        )
        self.latest = snap
        return snap

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap = self._sample()
                if snap is None or self._stop.is_set():
                    break
                for cb in list(self._callbacks):
                    if self._stop.is_set():
                        break
                    try:
                        cb(snap)
                    except Exception:
                        pass
                # Faster polling while HoN is open
                wait = self._game_interval if (snap and snap.game_found) else self._idle_interval
            except Exception:
                wait = self._idle_interval
            if self._stop.wait(wait):
                break


def format_rate(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"
