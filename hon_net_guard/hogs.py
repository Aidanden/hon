"""Network Task Manager — find processes eating bandwidth / causing timeouts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil

# Known bandwidth hogs that commonly cause gaming timeouts.
KNOWN_HOGS: dict[str, str] = {
    # Browsers / web
    "chrome": "Browser downloads / tabs",
    "chrome.exe": "Browser downloads / tabs",
    "chromium": "Browser downloads / tabs",
    "msedge": "Browser downloads / tabs",
    "msedge.exe": "Browser downloads / tabs",
    "firefox": "Browser downloads / tabs",
    "firefox.exe": "Browser downloads / tabs",
    "brave": "Browser downloads / tabs",
    "brave.exe": "Browser downloads / tabs",
    # Launchers / stores
    "steam": "Steam downloads / cloud",
    "steam.exe": "Steam downloads / cloud",
    "steamwebhelper": "Steam web helper",
    "steamwebhelper.exe": "Steam web helper",
    "epicgameslauncher": "Epic downloads",
    "epicgameslauncher.exe": "Epic downloads",
    "origin.exe": "EA / Origin",
    "eadesktop.exe": "EA App",
    "battle.net.exe": "Battle.net",
    "agent.exe": "Battle.net agent",
    # Chat / voice
    "discord": "Discord upload/stream",
    "discord.exe": "Discord upload/stream",
    "slack": "Slack sync",
    "teams": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "skype.exe": "Skype",
    # Cloud / sync
    "onedrive": "OneDrive sync",
    "onedrive.exe": "OneDrive sync",
    "dropbox": "Dropbox sync",
    "dropbox.exe": "Dropbox sync",
    "googledrivefs.exe": "Google Drive sync",
    "megasync": "MEGA sync",
    "megasync.exe": "MEGA sync",
    # Torrents / P2P
    "qbittorrent": "Torrent client",
    "qbittorrent.exe": "Torrent client",
    "transmission-gtk": "Torrent client",
    "transmission-qt": "Torrent client",
    "deluge": "Torrent client",
    "utorrent.exe": "Torrent client",
    "bitcomet.exe": "Torrent client",
    # Updates / OS
    "tiworker.exe": "Windows Update",
    "usocoreworker.exe": "Windows Update",
    "mousocoreworker.exe": "Windows Update",
    "wuauclt.exe": "Windows Update",
    "dosvc": "Delivery Optimization",
    "deliveryoptimization": "Delivery Optimization",
    "packagekitd": "Linux package updates",
    "dnf": "Fedora package manager",
    "apt": "APT package manager",
    "yum": "YUM package manager",
    "flatpak": "Flatpak downloads",
    "snapd": "Snap downloads",
    # Media
    "spotify": "Spotify streaming",
    "spotify.exe": "Spotify streaming",
    "obs": "OBS streaming/recording",
    "obs64.exe": "OBS streaming/recording",
    # Misc
    "parsec": "Parsec remote",
    "anydesk": "Remote desktop",
    "teamviewer": "Remote desktop",
}

# Clean known hogs keys
KNOWN_HOGS = {k.lower(): v for k, v in KNOWN_HOGS.items()}

GAME_MARKERS = (
    "juvio",
    "hon.exe",
    "hon_x64",
    "heroesofnewerth",
    "heroes of newerth",
)

SAFE_NEVER_KILL = {
    "systemd",
    "init",
    "kthreadd",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "explorer.exe",
    "dwm.exe",
    "fontdrvhost.exe",
    "hon_net_guard",
    "python",
    "python3",
    "python3.14",
    "python3.13",
    "python3.12",
    "python3.11",
}


@dataclass
class HogInfo:
    pid: int
    name: str
    connections: int = 0
    established: int = 0
    activity: float = 0.0  # rough bytes/sec from io deltas when networked
    risk: str = "low"  # low | medium | high | game
    reason: str = ""
    score: float = 0.0
    cmdline: str = ""

    @property
    def can_kill(self) -> bool:
        base = self.name.lower()
        if self.risk == "game":
            return False
        if base in SAFE_NEVER_KILL:
            return False
        if base.startswith("python"):
            return False
        return True


@dataclass
class HogScanResult:
    timestamp: float
    hogs: list[HogInfo] = field(default_factory=list)
    total_connections: int = 0


class NetworkHogScanner:
    """Ranks processes that are most likely eating the internet."""

    def __init__(self) -> None:
        self._prev_io: dict[int, tuple[int, int, float]] = {}
        self._last: HogScanResult | None = None

    def scan(self, top_n: int = 15) -> HogScanResult:
        now = time.time()
        by_pid: dict[int, HogInfo] = {}
        total_conns = 0

        # 1) Connections map
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.Error, PermissionError):
            conns = []

        for c in conns:
            if not c.pid:
                continue
            total_conns += 1
            info = by_pid.get(c.pid)
            if info is None:
                info = HogInfo(pid=c.pid, name="?")
                by_pid[c.pid] = info
            info.connections += 1
            if c.status == psutil.CONN_ESTABLISHED:
                info.established += 1

        # 2) Enrich with names / cmdline / io activity
        for pid, info in list(by_pid.items()):
            try:
                proc = psutil.Process(pid)
                name = proc.name() or f"pid-{pid}"
                info.name = name
                try:
                    cmd = " ".join(proc.cmdline())
                except (psutil.Error, OSError):
                    cmd = ""
                info.cmdline = cmd[:180]

                # IO activity (disk+net mixed, but useful when process has sockets)
                try:
                    io = proc.io_counters()
                    read_b = int(getattr(io, "read_bytes", 0) or 0)
                    write_b = int(getattr(io, "write_bytes", 0) or 0)
                    prev = self._prev_io.get(pid)
                    if prev:
                        dt = max(now - prev[2], 0.001)
                        info.activity = max(0.0, ((read_b - prev[0]) + (write_b - prev[1])) / dt)
                    self._prev_io[pid] = (read_b, write_b, now)
                except (psutil.Error, OSError):
                    pass

                info.risk, info.reason = self._classify(name, cmd)
                info.score = self._score(info)
            except (psutil.Error, OSError):
                by_pid.pop(pid, None)

        # 3) Also surface known hogs even with few/no sockets yet (just started download)
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid = int(proc.info["pid"])
                name = (proc.info.get("name") or "").lower()
                if pid in by_pid:
                    continue
                reason = KNOWN_HOGS.get(name)
                if not reason:
                    # partial match
                    reason = next((v for k, v in KNOWN_HOGS.items() if k in name), None)
                if not reason:
                    continue
                info = HogInfo(
                    pid=pid,
                    name=proc.info.get("name") or name,
                    connections=0,
                    established=0,
                    risk="high",
                    reason=reason,
                )
                info.score = self._score(info) + 25
                by_pid[pid] = info
            except (psutil.Error, OSError, TypeError, ValueError):
                continue

        ranked = sorted(by_pid.values(), key=lambda h: h.score, reverse=True)
        result = HogScanResult(timestamp=now, hogs=ranked[:top_n], total_connections=total_conns)
        self._last = result
        # Prune stale io cache
        live = {h.pid for h in ranked}
        self._prev_io = {k: v for k, v in self._prev_io.items() if k in live}
        return result

    def _classify(self, name: str, cmdline: str) -> tuple[str, str]:
        blob = f"{name} {cmdline}".lower()
        if any(m in blob for m in GAME_MARKERS):
            return "game", "HoN / Juvio (keep running)"

        key = name.lower()
        if key in KNOWN_HOGS:
            return "high", KNOWN_HOGS[key]
        for k, reason in KNOWN_HOGS.items():
            if k in key or k in blob:
                return "high", reason

        if key in SAFE_NEVER_KILL:
            return "low", "System process"

        return "medium", "Active network sockets"

    def _score(self, info: HogInfo) -> float:
        score = 0.0
        score += info.established * 8
        score += info.connections * 2
        # activity: MB/s * weight
        score += min(info.activity / (256 * 1024), 40)  # cap contribution
        if info.risk == "high":
            score += 35
        elif info.risk == "game":
            score += 10
        elif info.risk == "medium":
            score += 8
        return score


def kill_process(pid: int) -> tuple[bool, str]:
    """Terminate a process (safe-guarded)."""
    try:
        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        if name in SAFE_NEVER_KILL or name.startswith("python"):
            return False, f"Refused to kill protected process: {name}"
        blob = " ".join(proc.cmdline()).lower() if proc.cmdline() else name
        if any(m in blob for m in GAME_MARKERS):
            return False, "Refused to kill the game process"
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except psutil.TimeoutExpired:
            proc.kill()
        return True, f"Killed PID {pid} ({name})"
    except psutil.NoSuchProcess:
        return False, f"PID {pid} already gone"
    except psutil.AccessDenied:
        return False, f"Access denied for PID {pid} (need Admin/root)"
    except Exception as exc:
        return False, str(exc)


def kill_high_risk(hogs: list[HogInfo], limit: int = 8) -> list[str]:
    messages: list[str] = []
    killed = 0
    for hog in hogs:
        if killed >= limit:
            break
        if hog.risk != "high" or not hog.can_kill:
            continue
        ok, msg = kill_process(hog.pid)
        messages.append(msg)
        if ok:
            killed += 1
    if not messages:
        messages.append("No high-risk hogs to kill.")
    return messages


def format_activity(bps: float) -> str:
    if bps <= 0:
        return "—"
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.2f} MB/s"
