"""Process + network monitoring for HoN and overall link health."""

from __future__ import annotations

import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import psutil

from .config import CMDLINE_MARKERS, Settings


@dataclass
class ProcessNetStats:
    name: str
    pid: int
    # Bytes/sec averaged over the sample window.
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


def _ping_once(host: str, timeout_sec: float = 2.0) -> tuple[bool, float | None]:
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_sec * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_sec)), host]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 1.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return False, None
        import re

        match = re.search(r"time[=<]\s*([\d.]+)\s*ms", out, re.IGNORECASE)
        if match:
            return True, float(match.group(1))
        return True, None
    except Exception:
        return False, None


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

    def on_update(self, callback: Callable[[Snapshot], None]) -> None:
        self._callbacks.append(callback)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _target_names(self) -> set[str]:
        return {n.strip().lower() for n in self.settings.process_names if n.strip()}

    def _sample(self) -> Snapshot:
        now = time.time()
        names = self._target_names()
        procs: list[ProcessNetStats] = []
        game_down = 0.0
        game_up = 0.0

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
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
                stats = ProcessNetStats(name=name, pid=proc.pid, down_bps=down_bps, up_bps=up_bps)
                procs.append(stats)
            except (psutil.Error, OSError):
                continue

        nic = psutil.net_io_counters()
        total_down = total_up = 0.0
        if self._prev_nic:
            dt = max(now - self._prev_nic[2], 0.001)
            total_down = max(0.0, (nic.bytes_recv - self._prev_nic[0]) / dt)
            total_up = max(0.0, (nic.bytes_sent - self._prev_nic[1]) / dt)
        self._prev_nic = (nic.bytes_recv, nic.bytes_sent, now)

        game_found = bool(procs)
        if game_found:
            game_down = total_down
            game_up = total_up

        link_bps = max(self.settings.link_mbps * 1_000_000 / 8.0, 1.0)
        saturating = total_down >= link_bps * 0.85 or total_up >= link_bps * 0.85

        ping_ok, ping_ms = _ping_once(self.settings.ping_host)

        snap = Snapshot(
            timestamp=now,
            game_found=game_found,
            processes=procs,
            total_down_bps=total_down,
            total_up_bps=total_up,
            game_down_bps=game_down,
            game_up_bps=game_up,
            ping_ms=ping_ms,
            ping_ok=ping_ok,
            saturating=saturating,
        )
        self.latest = snap
        return snap

    def _loop(self) -> None:
        try:
            self._sample()
        except Exception:
            pass
        while not self._stop.wait(self.interval):
            try:
                snap = self._sample()
                for cb in list(self._callbacks):
                    try:
                        cb(snap)
                    except Exception:
                        pass
            except Exception:
                continue


def format_rate(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"
