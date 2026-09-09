"""Ping measurement + latency boost helpers."""

from __future__ import annotations

import statistics
import subprocess
import time
from dataclasses import dataclass, field

from . import qos
from .monitor import _ping_once
from .qos import CommandResult


@dataclass
class PingSample:
    ok_count: int = 0
    fail_count: int = 0
    values_ms: list[float] = field(default_factory=list)

    @property
    def loss_pct(self) -> float:
        total = self.ok_count + self.fail_count
        if total <= 0:
            return 100.0
        return 100.0 * self.fail_count / total

    @property
    def avg(self) -> float | None:
        return statistics.fmean(self.values_ms) if self.values_ms else None

    @property
    def jitter(self) -> float | None:
        if len(self.values_ms) < 2:
            return 0.0 if self.values_ms else None
        diffs = [
            abs(self.values_ms[i] - self.values_ms[i - 1])
            for i in range(1, len(self.values_ms))
        ]
        return statistics.fmean(diffs)

    @property
    def max_ms(self) -> float | None:
        return max(self.values_ms) if self.values_ms else None


def measure_ping(host: str, count: int = 6, gap: float = 0.25) -> PingSample:
    sample = PingSample()
    for _ in range(count):
        ok, ms = _ping_once(host, timeout_sec=1.5)
        if ok and ms is not None:
            sample.ok_count += 1
            sample.values_ms.append(ms)
        else:
            sample.fail_count += 1
        time.sleep(gap)
    return sample


def congestion_improvement_pct(before: PingSample, after: PingSample) -> float:
    """Estimate how much congestion-related ping pain was removed (0–100)."""
    score = 0.0

    # Loss / timeouts (biggest gaming killer)
    before_loss = before.loss_pct
    after_loss = after.loss_pct
    if before_loss > 0:
        recovered = max(0.0, before_loss - after_loss) / before_loss
        score += 40.0 * recovered
    elif after_loss == 0:
        score += 40.0
    else:
        score += max(0.0, 40.0 - after_loss)

    # Average latency drop
    if before.avg and after.avg and before.avg > 0:
        drop = max(0.0, before.avg - after.avg) / before.avg
        score += 30.0 * min(1.0, drop * 1.25)
    elif after.avg is not None and after.loss_pct == 0:
        score += 20.0

    # Jitter / spikes
    if before.jitter is not None and after.jitter is not None:
        if before.jitter > 1:
            drop_j = max(0.0, before.jitter - after.jitter) / before.jitter
            score += 30.0 * drop_j
        elif after.jitter is not None and after.jitter <= 5:
            score += 30.0
    elif after.jitter is not None and after.jitter <= 5 and after.loss_pct == 0:
        score += 25.0

    return max(0.0, min(100.0, score))


def stability_score(
    *,
    active: bool,
    max_mode: bool,
    saturating: bool,
    ping_ok: bool,
    ping_ms: float | None,
    jitter_ms: float | None,
    loss_pct: float,
    measured_improve: float | None,
) -> float:
    """Live 0–100 score. Reaches 100 when max-ping mode is fully healthy."""
    if not active:
        return 0.0

    score = 35.0  # shaping online
    if max_mode:
        score += 15.0  # aggressive profile applied

    if not saturating:
        score += 15.0
    if ping_ok:
        score += 15.0
    if loss_pct <= 0.1:
        score += 10.0
    if jitter_ms is not None and jitter_ms <= 8:
        score += 5.0
    if ping_ms is not None and ping_ms < 120:
        score += 5.0

    if measured_improve is not None:
        # Blend measured congestion recovery toward the ceiling.
        score = max(score, 50.0 + measured_improve * 0.5)

    # Cap: true 100 when max-ping mode is fully healthy.
    if max_mode and not saturating and ping_ok and loss_pct <= 0.1:
        if jitter_ms is None or jitter_ms <= 12:
            return 100.0
        if measured_improve is not None and measured_improve >= 80:
            return 100.0

    return max(0.0, min(100.0, score))


def apply_linux_latency_tweaks() -> CommandResult:
    """Best-effort sysctl tweaks for lower gaming latency (root)."""
    if not qos.is_linux() or not qos.is_admin():
        return CommandResult(False, "", "linux root required", -1)

    tweaks = {
        "net.ipv4.tcp_fastopen": "3",
        "net.ipv4.tcp_slow_start_after_idle": "0",
        "net.ipv4.tcp_mtu_probing": "1",
        "net.core.default_qdisc": "fq_codel",
        "net.ipv4.tcp_congestion_control": "bbr",
    }
    ok_n = 0
    notes: list[str] = []
    for key, value in tweaks.items():
        try:
            proc = subprocess.run(
                ["sysctl", "-w", f"{key}={value}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                ok_n += 1
            else:
                notes.append(f"{key}:{(proc.stderr or '').strip()}")
        except Exception as exc:
            notes.append(f"{key}:{exc}")

    # Prefer low-latency busy polling lightly if available (safe no-op if missing)
    for key, value in (
        ("net.core.busy_read", "50"),
        ("net.core.busy_poll", "50"),
    ):
        subprocess.run(
            ["sysctl", "-w", f"{key}={value}"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    return CommandResult(
        ok_n > 0,
        f"sysctl_ok={ok_n}",
        "; ".join(notes[:4]),
        0 if ok_n else -1,
    )


def apply_windows_latency_tweaks() -> CommandResult:
    """Disable Nagle-ish delays + game-friendly network stack tweaks."""
    if not qos.is_windows() or not qos.is_admin():
        return CommandResult(False, "", "windows admin required", -1)

    from .qos_windows import _run_ps

    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
# Network Throttling Index — don't throttle multimedia/game traffic
New-Item -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile' -Name 'NetworkThrottlingIndex' -Type DWord -Value 0xffffffff
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile' -Name 'SystemResponsiveness' -Type DWord -Value 0

# Games task profile
$games = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games'
New-Item -Path $games -Force | Out-Null
Set-ItemProperty -Path $games -Name 'GPU Priority' -Type DWord -Value 8
Set-ItemProperty -Path $games -Name 'Priority' -Type DWord -Value 6
Set-ItemProperty -Path $games -Name 'Scheduling Category' -Type String -Value 'High'
Set-ItemProperty -Path $games -Name 'SFIO Priority' -Type String -Value 'High'

# TcpAckFrequency / TCPNoDelay on active interfaces
Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces' | ForEach-Object {
  Set-ItemProperty -Path $_.PSPath -Name 'TcpAckFrequency' -Type DWord -Value 1 -Force
  Set-ItemProperty -Path $_.PSPath -Name 'TCPNoDelay' -Type DWord -Value 1 -Force
}

# Prefer low-latency timer resolution hint via power plan (best effort)
powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN 100 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null
'OK'
"""
    return _run_ps(script)
