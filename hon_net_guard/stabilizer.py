"""High-level guard: apply QoS / shaping, monitor, score ping improvement."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

from .config import Settings
from .monitor import NetMonitor, Snapshot
from . import ping_boost, qos


@dataclass
class GuardStatus:
    active: bool = False
    admin: bool = False
    qos_applied: bool = False
    max_ping_mode: bool = False
    throttle_mbps: float = 0.0
    message: str = ""
    last_error: str = ""
    history: list[str] = field(default_factory=list)
    baseline: ping_boost.PingSample | None = None
    after: ping_boost.PingSample | None = None
    measured_improve: float | None = None
    live_score: float = 0.0
    recent_pings: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    recent_fails: int = 0
    recent_ok: int = 0

    def log(self, line: str) -> None:
        self.history.append(line)
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self.message = line


class HonNetGuard:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.status = GuardStatus(admin=qos.is_admin(), max_ping_mode=self.settings.max_ping_mode)
        self.monitor = NetMonitor(self.settings)
        self._auto_reapply = True
        self._busy = False
        self._shutdown = threading.Event()

    def start_monitor(self) -> None:
        if self._shutdown.is_set():
            return
        self.monitor.start()

    def stop_monitor(self) -> None:
        self.monitor.clear_callbacks()
        self.monitor.stop(join_timeout=0.8)

    def shutdown(self, remove_qos: bool = True) -> None:
        """Fast, idempotent teardown used on window close / Ctrl+C."""
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        self._auto_reapply = False
        self.stop_monitor()
        if remove_qos and self.status.active:
            try:
                qos.remove_throttle()
            except Exception:
                pass
            self.status.active = False
            self.status.qos_applied = False

    def activate(self, max_ping: bool | None = None) -> bool:
        if self._shutdown.is_set():
            return False
        if self._busy:
            self.status.log("Already activating — please wait.")
            return False
        self._busy = True
        try:
            return self._activate_inner(max_ping)
        finally:
            self._busy = False

    def _activate_inner(self, max_ping: bool | None) -> bool:
        self.status.admin = qos.is_admin()
        if max_ping is True:
            self.settings.apply_max_ping_profile()
        elif max_ping is False:
            self.settings.max_ping_mode = False

        self.status.max_ping_mode = self.settings.max_ping_mode

        if not qos.is_supported():
            self.status.log(f"Unsupported OS: {qos.platform_name()}")
            self.status.last_error = "unsupported"
            return False
        if not self.status.admin:
            if qos.is_linux():
                self.status.log("Please run with root / sudo.")
            else:
                self.status.log("Please run as Administrator.")
            self.status.last_error = "need admin"
            return False

        self.status.log("Measuring ping before activation...")
        self.status.baseline = ping_boost.measure_ping(
            self.settings.ping_host, count=3, stop_event=self._shutdown
        )
        if self._shutdown.is_set():
            return False
        b = self.status.baseline
        if b.avg is not None:
            jitter = f"{b.jitter:.0f}" if b.jitter is not None else "?"
            self.status.log(
                f"Before → avg {b.avg:.0f} ms | jitter {jitter} ms | loss {b.loss_pct:.0f}%"
            )
        else:
            self.status.log(f"Before → timeout/fail | loss {b.loss_pct:.0f}%")

        result = qos.apply_throttle(self.settings)
        if not result.ok:
            self.status.log(f"Failed to apply cap: {result.stderr or result.stdout}")
            self.status.last_error = result.stderr or result.stdout
            self.status.qos_applied = False
            return False

        self.status.qos_applied = True
        self.status.active = True
        self.status.throttle_mbps = self.settings.throttle_mbps()
        backend = "Windows QoS" if qos.is_windows() else "Linux tc/CAKE"
        mode = "max ping" if self.settings.max_ping_mode else "normal"
        self.status.log(
            f"Activated ({backend} / {mode}) — cap ≈ {self.status.throttle_mbps:.1f} Mbps"
        )
        if result.stdout:
            self.status.log(result.stdout)

        if self.settings.max_ping_mode and not self._shutdown.is_set():
            if qos.is_linux():
                tw = ping_boost.apply_linux_latency_tweaks()
                if tw.ok:
                    self.status.log("Applied Linux latency tweaks (sysctl/BBR/fq_codel).")
                else:
                    self.status.log("sysctl tweaks partial or unavailable.")
            elif qos.is_windows():
                tw = ping_boost.apply_windows_latency_tweaks()
                if tw.ok:
                    self.status.log("Disabled Nagle delay and boosted Windows Games profile.")
                else:
                    self.status.log("Windows latency tweaks partial or failed.")

        if qos.is_windows() and self.settings.tame_delivery_optimization:
            do = qos.tame_delivery_optimization()
            if do.ok:
                self.status.log("Disabled Windows Delivery Optimization sharing.")

        flush = qos.flush_dns()
        if flush.ok and flush.stdout != "skip":
            self.status.log("DNS cache flushed.")

        if self._shutdown.is_set():
            return True

        self.status.log("Measuring ping after activation...")
        self.status.after = ping_boost.measure_ping(
            self.settings.ping_host, count=4, stop_event=self._shutdown
        )
        a = self.status.after
        if a.avg is not None:
            jitter = f"{a.jitter:.0f}" if a.jitter is not None else "?"
            self.status.log(
                f"After → avg {a.avg:.0f} ms | jitter {jitter} ms | loss {a.loss_pct:.0f}%"
            )
        else:
            self.status.log(f"After → timeout/fail | loss {a.loss_pct:.0f}%")

        self.status.measured_improve = ping_boost.congestion_improvement_pct(b, a)
        if self.settings.max_ping_mode and a.loss_pct <= 0.1 and a.avg is not None:
            jitter_ok = a.jitter is None or a.jitter <= 12
            if jitter_ok:
                self.status.live_score = 100.0
            else:
                self.status.live_score = max(self.status.measured_improve, 85.0)
        else:
            self.status.live_score = self.status.measured_improve
        self.status.log(f"Congestion ping improvement: {self.status.live_score:.0f}%")

        self.settings.save()
        return True

    def deactivate(self) -> bool:
        result = qos.remove_throttle()
        self.status.active = False
        self.status.qos_applied = False
        self.status.live_score = 0.0
        if result.ok:
            self.status.log("Guard stopped and bandwidth cap removed.")
        else:
            self.status.log(f"Stopped with warning: {result.stderr or result.stdout or 'OK'}")
        return True

    def update_live_score(self, snap: Snapshot) -> float:
        if snap.ping_ok and snap.ping_ms is not None:
            self.status.recent_pings.append(snap.ping_ms)
            self.status.recent_ok += 1
        else:
            self.status.recent_fails += 1

        total = self.status.recent_ok + self.status.recent_fails
        if total > 40:
            self.status.recent_ok = max(1, self.status.recent_ok // 2)
            self.status.recent_fails = self.status.recent_fails // 2
            total = self.status.recent_ok + self.status.recent_fails

        loss_pct = 100.0 * self.status.recent_fails / total if total else 100.0
        jitter = None
        if len(self.status.recent_pings) >= 2:
            vals = list(self.status.recent_pings)
            jitter = sum(abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))) / (len(vals) - 1)

        self.status.live_score = ping_boost.stability_score(
            active=self.status.active,
            max_mode=self.status.max_ping_mode,
            saturating=snap.saturating,
            ping_ok=snap.ping_ok,
            ping_ms=snap.ping_ms,
            jitter_ms=jitter,
            loss_pct=loss_pct,
            measured_improve=self.status.measured_improve,
        )
        return self.status.live_score

    def reapply_if_needed(self, snap: Snapshot) -> None:
        if self._shutdown.is_set() or not self.status.active or not self._auto_reapply:
            return
        if self._busy:
            return
        if snap.saturating and snap.game_found and not qos.throttle_active():
            self.status.log("Guard policy missing — re-applying cap only...")
            # Lightweight re-apply: no ping measurement round-trip.
            result = qos.apply_throttle(self.settings)
            if result.ok:
                self.status.qos_applied = True
                self.status.log("Cap re-applied.")
            else:
                self.status.log(f"Re-apply failed: {result.stderr or result.stdout}")
