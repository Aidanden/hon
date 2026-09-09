"""Default settings for HoN Net Guard."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Common HoN Reborn / classic process names (Windows + Wine exe names)
DEFAULT_PROCESS_NAMES = [
    "juvio.exe",
    "hon.exe",
    "hon_x64.exe",
    "HeroesOfNewerth.exe",
    "crashpad_handler.exe",
]

# Substrings matched against process cmdline (Linux/Wine friendly)
CMDLINE_MARKERS = (
    "juvio",
    "juvio.exe",
    "hon.exe",
    "hon_x64.exe",
    "heroes of newerth",
    "heroesofnewerth",
)

QOS_POLICY_NAME = "HoNNetGuardThrottle"
CONFIG_PATH = Path.home() / ".hon_net_guard.json"

# Max-ping profile: leave lots of headroom so ACKs/game packets never queue.
MAX_PING_SHARE = 0.38


@dataclass
class Settings:
    # Approximate home link speed in Mbps (download). Used to leave headroom.
    link_mbps: float = 20.0
    # Max share of the link used for shaped bandwidth (0.1–0.95).
    game_share: float = 0.45
    # Absolute floor / ceiling for the throttle (Mbps).
    min_throttle_mbps: float = 1.5
    max_throttle_mbps: float = 50.0
    # Extra process names the user can add.
    process_names: list[str] = field(default_factory=lambda: list(DEFAULT_PROCESS_NAMES))
    # Ping target for live latency checks.
    ping_host: str = "1.1.1.1"
    # Apply Windows Delivery Optimization caps while guarding.
    tame_delivery_optimization: bool = True
    # Apply DSCP EF marking (helps if router honors QoS).
    mark_dscp: bool = True
    # Aggressive latency profile (sysctl / Nagle / cake gaming flags).
    max_ping_mode: bool = True

    def throttle_mbps(self) -> float:
        share = MAX_PING_SHARE if self.max_ping_mode else self.game_share
        raw = self.link_mbps * share
        return max(self.min_throttle_mbps, min(self.max_throttle_mbps, raw))

    def throttle_bits_per_second(self) -> int:
        return int(self.throttle_mbps() * 1_000_000)

    def apply_max_ping_profile(self) -> None:
        self.max_ping_mode = True
        self.game_share = MAX_PING_SHARE
        self.mark_dscp = True
        self.tame_delivery_optimization = True

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
