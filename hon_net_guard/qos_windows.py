"""Windows QoS helpers via PowerShell (admin required)."""

from __future__ import annotations

import subprocess

from .config import QOS_POLICY_NAME, Settings
from .qos import CommandResult


def _run_ps(script: str, timeout: int = 45) -> CommandResult:
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return CommandResult(
            ok=proc.returncode == 0,
            stdout=(proc.stdout or "").strip(),
            stderr=(proc.stderr or "").strip(),
            code=proc.returncode,
        )
    except Exception as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc), code=-1)


def throttle_active() -> bool:
    result = _run_ps(
        "Get-NetQosPolicy -ErrorAction SilentlyContinue "
        f"| Where-Object {{ $_.Name -like '{QOS_POLICY_NAME}*' }} "
        "| Select-Object -ExpandProperty Name"
    )
    return bool(result.ok and result.stdout.strip())


def remove_throttle() -> CommandResult:
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
Get-NetQosPolicy -ErrorAction SilentlyContinue | Where-Object {{ $_.Name -like '{QOS_POLICY_NAME}*' }} | Remove-NetQosPolicy -Confirm:$false
'OK'
"""
    return _run_ps(script)


def apply_throttle(settings: Settings) -> CommandResult:
    bits = settings.throttle_bits_per_second()
    apps: list[str] = []
    for name in settings.process_names:
        clean = name.strip().lower()
        if clean.endswith(".exe") and clean not in apps:
            apps.append(clean)
    if not apps:
        apps = ["juvio.exe"]

    parts = [
        "$ErrorActionPreference = 'Stop'",
        f"Get-NetQosPolicy -ErrorAction SilentlyContinue | Where-Object {{ $_.Name -like '{QOS_POLICY_NAME}*' }} | Remove-NetQosPolicy -Confirm:$false",
    ]
    for idx, app in enumerate(apps):
        policy = QOS_POLICY_NAME if idx == 0 else f"{QOS_POLICY_NAME}_{idx}"
        dscp = " -DSCPAction 46" if settings.mark_dscp and idx == 0 else ""
        parts.append(
            f"New-NetQosPolicy -Name '{policy}' "
            f"-AppPathNameMatchCondition '{app}' "
            f"-IPProtocolMatchCondition Both "
            f"-ThrottleRateActionBitsPerSecond {bits} "
            f"-NetworkProfile All{dscp} | Out-Null"
        )
    parts.append(f"'APPLIED:{bits}'")
    return _run_ps("\n".join(parts))


def tame_delivery_optimization() -> CommandResult:
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
New-Item -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DeliveryOptimization\Config' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DeliveryOptimization\Config' -Name 'DODownloadMode' -Type DWord -Value 0
try { Set-DeliveryOptimizationStatus -DownloadMode 0 | Out-Null } catch {}
'OK'
"""
    return _run_ps(script)


def flush_dns() -> CommandResult:
    return _run_ps("Clear-DnsClientCache; ipconfig /flushdns | Out-Null; 'OK'")
