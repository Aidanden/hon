"""Moment-by-moment HoN / Juvio tracking + net-hog service control."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections import deque

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

# Main game binaries — never auto-kill
CORE_NAMES = {
    "juvio.exe",
    "hon.exe",
    "hon_x64.exe",
    "heroesofnewerth.exe",
}

# HoN-related services that often suck bandwidth / cause timeouts
STOPPABLE_SERVICE_NAMES = {
    "crashpad_handler.exe": "Crash reporter (often downloads / uploads dumps)",
    "crashpad_handler": "Crash reporter",
}

HON_PATH_MARKERS = (
    "juvio",
    "heroes of newerth",
    "heroesofnewerth",
    "hon reborn",
    "honreborn",
    "\\hon\\",
    "/hon/",
)


@dataclass
class HonProcLive:
    pid: int
    name: str
    cpu_pct: float = 0.0
    ram_mb: float = 0.0
    threads: int = 0
    connections: int = 0
    established: int = 0
    activity_bps: float = 0.0
    status: str = ""
    create_time: float = 0.0
    remotes: list[str] = field(default_factory=list)
    role: str = "helper"  # core | service | helper | downloader
    net_hog: bool = False
    can_stop: bool = False
    reason: str = ""


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
    hog_count: int = 0
    stoppable: list[HonProcLive] = field(default_factory=list)
    # Filled by monitor/GUI from live ping
    ping_ms: float | None = None
    ping_ok: bool = False
    ping_history: list[float] = field(default_factory=list)


class HonLiveTracker:
    """Watches HoN continuously, flags net-hog services, supports stop/fix."""

    def __init__(self) -> None:
        self._seen_pids: set[int] = set()
        self._session_start: float | None = None
        self._cpu_primed: set[int] = set()
        self._prev_io: dict[int, tuple[int, int, float]] = {}
        self._ping_history: deque[float] = deque(maxlen=30)

    def reset_session(self) -> None:
        self._session_start = None
        self._seen_pids.clear()

    def note_ping(self, ok: bool, ms: float | None) -> None:
        if ok and ms is not None:
            self._ping_history.append(ms)

    def ping_history(self) -> list[float]:
        return list(self._ping_history)

    def _is_hon_related(self, name: str, cmdline: str) -> bool:
        n = name.lower()
        if n in GAME_NAME_SET or n in STOPPABLE_SERVICE_NAMES:
            return True
        blob = f"{n} {cmdline}".lower()
        if any(m in blob for m in CMDLINE_MARKERS):
            return True
        if any(m in blob for m in HON_PATH_MARKERS):
            return True
        return False

    def _classify(self, name: str, cmdline: str, established: int, activity: float) -> tuple[str, bool, bool, str]:
        n = name.lower()
        blob = f"{n} {cmdline}".lower()

        if n in CORE_NAMES or any(c in n for c in ("juvio.exe", "hon.exe", "hon_x64")):
            hog = activity > 2 * 1024 * 1024 or established > 80
            return "core", hog, False, "Main game client (protected)"

        if n in STOPPABLE_SERVICE_NAMES or "crashpad" in n:
            reason = STOPPABLE_SERVICE_NAMES.get(n, "Crash/report service")
            return "service", True, True, reason

        # Wine helper hosting HoN assets / updates
        if n in WINE_HOSTS and any(m in blob for m in HON_PATH_MARKERS + CMDLINE_MARKERS):
            hog = activity > 512 * 1024 or established > 20
            return "helper", hog, hog, "Wine helper for HoN (stop if hogging)"

        # Generic HoN-path process with heavy IO / sockets → likely downloader
        if any(m in blob for m in HON_PATH_MARKERS):
            if activity > 256 * 1024 or established > 15:
                return "downloader", True, True, "HoN-related download / sync activity"
            return "helper", False, True, "HoN-related helper"

        if activity > 1 * 1024 * 1024 and established > 10:
            return "downloader", True, True, "High network activity near HoN"

        return "helper", False, False, "HoN-related process"

    def sample(self) -> HonLiveState:
        now = time.time()
        procs: list[HonProcLive] = []
        current_pids: set[int] = set()

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "")
                low = name.lower()
                try:
                    cmdline = " ".join(psutil.Process(proc.info["pid"]).cmdline())
                except (psutil.Error, OSError):
                    cmdline = ""

                # Broader scan: any .exe / wine / known names that look HoN-related
                if low not in GAME_NAME_SET and low not in STOPPABLE_SERVICE_NAMES:
                    if not (
                        low in WINE_HOSTS
                        or low.endswith(".exe")
                        or any(m in f"{low} {cmdline}".lower() for m in HON_PATH_MARKERS + CMDLINE_MARKERS)
                    ):
                        continue
                    if not self._is_hon_related(low, cmdline):
                        continue

                p = psutil.Process(proc.info["pid"])
                pid = p.pid
                current_pids.add(pid)

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

                activity = 0.0
                try:
                    io = p.io_counters()
                    read_b = int(getattr(io, "read_bytes", 0) or 0)
                    write_b = int(getattr(io, "write_bytes", 0) or 0)
                    prev = self._prev_io.get(pid)
                    if prev:
                        dt = max(now - prev[2], 0.001)
                        activity = max(0.0, ((read_b - prev[0]) + (write_b - prev[1])) / dt)
                    self._prev_io[pid] = (read_b, write_b, now)
                except (psutil.Error, OSError):
                    pass

                est = 0
                total_c = 0
                remotes: list[str] = []
                try:
                    try:
                        conns_iter = p.net_connections(kind="inet")
                    except AttributeError:
                        conns_iter = p.connections(kind="inet")
                    for c in conns_iter:
                        total_c += 1
                        if c.status == psutil.CONN_ESTABLISHED:
                            est += 1
                        if c.raddr:
                            remotes.append(f"{c.raddr.ip}:{c.raddr.port}")
                except (psutil.Error, OSError):
                    pass

                role, net_hog, can_stop, reason = self._classify(low, cmdline, est, activity)
                procs.append(
                    HonProcLive(
                        pid=pid,
                        name=name or low,
                        cpu_pct=cpu,
                        ram_mb=mem,
                        threads=threads,
                        connections=total_c,
                        established=est,
                        activity_bps=activity,
                        status=status,
                        create_time=ctime,
                        remotes=remotes[:8],
                        role=role,
                        net_hog=net_hog,
                        can_stop=can_stop,
                        reason=reason,
                    )
                )
            except (psutil.Error, OSError):
                continue

        self._cpu_primed &= current_pids
        self._prev_io = {k: v for k, v in self._prev_io.items() if k in current_pids}

        running = bool(procs)
        just_opened = False
        just_closed = False

        if running and self._session_start is None:
            self._session_start = now
            just_opened = True
        if not running and self._session_start is not None:
            just_closed = True
            self._session_start = None

        new_pids = current_pids - self._seen_pids
        if running and new_pids and self._seen_pids:
            just_opened = True
        self._seen_pids = current_pids

        session_seconds = (now - self._session_start) if self._session_start else 0.0
        remotes: list[str] = []
        for p in procs:
            for r in p.remotes:
                if r not in remotes:
                    remotes.append(r)
        remotes = remotes[:12]

        primary = None
        for pref in ("juvio.exe", "hon.exe", "hon_x64.exe"):
            primary = next((p for p in procs if p.name.lower() == pref), None)
            if primary:
                break
        if primary is None and procs:
            primary = max(procs, key=lambda p: (p.role == "core", p.cpu_pct + p.established))

        stoppable = [p for p in procs if p.can_stop and (p.net_hog or p.role in ("service", "downloader"))]
        hogs = [p for p in procs if p.net_hog]

        return HonLiveState(
            running=running,
            just_opened=just_opened,
            just_closed=just_closed,
            session_seconds=session_seconds,
            process_count=len(procs),
            cpu_pct=sum(p.cpu_pct for p in procs),
            ram_mb=sum(p.ram_mb for p in procs),
            connections=sum(p.connections for p in procs),
            established=sum(p.established for p in procs),
            remotes=remotes,
            processes=sorted(procs, key=lambda p: (not p.net_hog, -p.activity_bps, -p.established)),
            primary_name=primary.name if primary else "",
            primary_pid=primary.pid if primary else 0,
            clock=time.strftime("%H:%M:%S"),
            hog_count=len(hogs),
            stoppable=stoppable,
            ping_history=list(self._ping_history),
        )


def format_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def format_activity(bps: float) -> str:
    if bps <= 0:
        return "—"
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"


def stop_hon_service(pid: int, *, allow_core: bool = False) -> tuple[bool, str]:
    """Stop a HoN-related service/helper. Protects core game unless allow_core."""
    try:
        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        if name in CORE_NAMES and not allow_core:
            return False, f"Refused to stop core game process: {name}"
        try:
            cmd = " ".join(proc.cmdline()).lower()
        except (psutil.Error, OSError):
            cmd = name
        # Extra safety: never kill plain system wine/server unless clearly HoN path
        if name in WINE_HOSTS and not any(m in cmd for m in HON_PATH_MARKERS + CMDLINE_MARKERS):
            return False, f"Refused to stop unrelated wine process PID {pid}"

        proc.terminate()
        try:
            proc.wait(timeout=2)
        except psutil.TimeoutExpired:
            proc.kill()
        return True, f"Stopped {name} (PID {pid})"
    except psutil.NoSuchProcess:
        return False, f"PID {pid} already gone"
    except psutil.AccessDenied:
        return False, f"Access denied for PID {pid} (need Admin/root)"
    except Exception as exc:
        return False, str(exc)


def fix_hon_net_hogs(state: HonLiveState) -> list[str]:
    """Stop HoN services/downloaders flagged as net hogs (not the core game)."""
    messages: list[str] = []
    targets = [p for p in state.processes if p.can_stop and (p.net_hog or p.role in ("service", "downloader"))]
    if not targets:
        messages.append("No HoN net-hog services to stop right now.")
        return messages
    for p in targets:
        ok, msg = stop_hon_service(p.pid)
        messages.append(msg if ok else f"Skip: {msg}")
    return messages
