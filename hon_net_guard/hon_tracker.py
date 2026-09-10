"""Moment-by-moment HoN / Juvio process tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil

from .config import CMDLINE_MARKERS, DEFAULT_PROCESS_NAMES

GAME_NAME_SET = {n.lower() for n in DEFAULT_PROCESS_NAMES}
WINE_HOSTS = {
    "wine",
    "wine64",
    "wine-preloader",
    "wine64-preloader",
    "wineserver",
}


@dataclass
class HonProcLive:
    pid: int
    name: str
    cpu_pct: float = 0.0
    ram_mb: float = 0.0
    threads: int = 0
    connections: int = 0
    established: int = 0
    status: str = ""
    create_time: float = 0.0
    remotes: list[str] = field(default_factory=list)


@dataclass
class HonLiveState:
    running: bool = False
    just_opened: bool = False
    just_closed: bool = False
    session_seconds: float = 0.0
    process_count: int = 0
    cpu_pct: float = 0.0
    ram_mb: float = 0.0
    connections: int = 0
    established: int = 0
    remotes: list[str] = field(default_factory=list)
    processes: list[HonProcLive] = field(default_factory=list)
    primary_name: str = ""
    primary_pid: int = 0
    clock: str = ""


class HonLiveTracker:
    """Watches HoN continuously and emits open/close edges."""

    def __init__(self) -> None:
        self._seen_pids: set[int] = set()
        self._session_start: float | None = None
        self._cpu_primed: set[int] = set()

    def reset_session(self) -> None:
        self._session_start = None
        self._seen_pids.clear()

    def _is_game(self, name: str, cmdline: str) -> bool:
        n = name.lower()
        if n in GAME_NAME_SET:
            return True
        blob = f"{n} {cmdline}".lower()
        return any(m in blob for m in CMDLINE_MARKERS)

    def sample(self) -> HonLiveState:
        now = time.time()
        procs: list[HonProcLive] = []
        current_pids: set[int] = set()

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "")
                low = name.lower()
                cmdline = ""
                if low not in GAME_NAME_SET:
                    if low in WINE_HOSTS or low.endswith(".exe"):
                        try:
                            cmdline = " ".join(proc.cmdline())
                        except (psutil.Error, OSError):
                            cmdline = ""
                    if not self._is_game(low, cmdline):
                        continue

                p = psutil.Process(proc.info["pid"])
                pid = p.pid
                current_pids.add(pid)

                # cpu_percent needs a prior call to be meaningful
                if pid not in self._cpu_primed:
                    p.cpu_percent(None)
                    self._cpu_primed.add(pid)
                    cpu = 0.0
                else:
                    cpu = float(p.cpu_percent(None) or 0.0)

                try:
                    mem = float(p.memory_info().rss) / (1024 * 1024)
                except (psutil.Error, OSError):
                    mem = 0.0
                try:
                    threads = int(p.num_threads())
                except (psutil.Error, OSError):
                    threads = 0
                try:
                    status = p.status()
                except (psutil.Error, OSError):
                    status = "?"
                try:
                    ctime = float(p.create_time())
                except (psutil.Error, OSError):
                    ctime = 0.0

                est = 0
                total_c = 0
                remotes: list[str] = []
                try:
                    conns_iter = p.net_connections(kind="inet")
                except AttributeError:
                    conns_iter = p.connections(kind="inet")
                try:
                    for c in conns_iter:
                        total_c += 1
                        if c.status == psutil.CONN_ESTABLISHED:
                            est += 1
                        if c.raddr:
                            remotes.append(f"{c.raddr.ip}:{c.raddr.port}")
                except (psutil.Error, OSError):
                    pass

                procs.append(
                    HonProcLive(
                        pid=pid,
                        name=name or low,
                        cpu_pct=cpu,
                        ram_mb=mem,
                        threads=threads,
                        connections=total_c,
                        established=est,
                        status=status,
                        create_time=ctime,
                        remotes=remotes[:8],
                    )
                )
            except (psutil.Error, OSError):
                continue

        # Drop primed cpu set for dead pids
        self._cpu_primed &= current_pids

        running = bool(procs)
        just_opened = False
        just_closed = False

        if running and self._session_start is None:
            self._session_start = now
            just_opened = True
        if not running and self._session_start is not None:
            just_closed = True
            self._session_start = None

        # Also treat brand-new pid while session already running
        new_pids = current_pids - self._seen_pids
        if running and new_pids and self._seen_pids:
            just_opened = True

        self._seen_pids = current_pids

        session_seconds = (now - self._session_start) if self._session_start else 0.0
        cpu_total = sum(p.cpu_pct for p in procs)
        ram_total = sum(p.ram_mb for p in procs)
        conns = sum(p.connections for p in procs)
        est_total = sum(p.established for p in procs)
        remotes: list[str] = []
        for p in procs:
            for r in p.remotes:
                if r not in remotes:
                    remotes.append(r)
        remotes = remotes[:12]

        # Prefer juvio/hon as primary
        primary = None
        for pref in ("juvio.exe", "hon.exe", "hon_x64.exe"):
            primary = next((p for p in procs if p.name.lower() == pref), None)
            if primary:
                break
        if primary is None and procs:
            primary = max(procs, key=lambda p: p.cpu_pct + p.established)

        clock = time.strftime("%H:%M:%S")
        return HonLiveState(
            running=running,
            just_opened=just_opened,
            just_closed=just_closed,
            session_seconds=session_seconds,
            process_count=len(procs),
            cpu_pct=cpu_total,
            ram_mb=ram_total,
            connections=conns,
            established=est_total,
            remotes=remotes,
            processes=procs,
            primary_name=primary.name if primary else "",
            primary_pid=primary.pid if primary else 0,
            clock=clock,
        )


def format_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"
