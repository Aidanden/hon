"""Linux traffic shaping via tc + IFB (root required)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .config import Settings
from .qos import CommandResult

IFB_NAME = "ifb-hon"
STATE_PATH = Path.home() / ".hon_net_guard_linux_state.json"


def _run(cmd: list[str], timeout: int = 30) -> CommandResult:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return CommandResult(
            ok=proc.returncode == 0,
            stdout=(proc.stdout or "").strip(),
            stderr=(proc.stderr or "").strip(),
            code=proc.returncode,
        )
    except Exception as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc), code=-1)


def _run_ok(cmd: list[str]) -> bool:
    return _run(cmd).ok


def default_iface() -> str | None:
    result = _run(["ip", "-json", "route", "show", "default"])
    if result.ok and result.stdout:
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list) and data:
                return data[0].get("dev")
        except json.JSONDecodeError:
            pass
    # Fallback parse
    result = _run(["ip", "route", "show", "default"])
    if not result.ok or not result.stdout:
        return None
    parts = result.stdout.split()
    if "dev" in parts:
        return parts[parts.index("dev") + 1]
    return None


def _save_state(iface: str, rate_mbit: float) -> None:
    STATE_PATH.write_text(
        json.dumps({"iface": iface, "ifb": IFB_NAME, "rate_mbit": rate_mbit}, indent=2),
        encoding="utf-8",
    )


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _clear_iface(iface: str) -> None:
    _run(["tc", "qdisc", "del", "dev", iface, "ingress"])
    _run(["tc", "qdisc", "del", "dev", iface, "root"])


def _clear_ifb(ifb: str = IFB_NAME) -> None:
    _run(["tc", "qdisc", "del", "dev", ifb, "root"])
    _run(["ip", "link", "set", "dev", ifb, "down"])
    _run(["ip", "link", "delete", "dev", ifb])


def throttle_active() -> bool:
    state = _load_state()
    iface = state.get("iface")
    if not iface:
        return False
    result = _run(["tc", "qdisc", "show", "dev", iface])
    if not result.ok:
        return False
    out = result.stdout.lower()
    return "cake" in out or "htb" in out or "fq_codel" in out


def remove_throttle() -> CommandResult:
    state = _load_state()
    iface = state.get("iface") or default_iface()
    ifb = state.get("ifb") or IFB_NAME
    errors: list[str] = []
    if iface:
        _clear_iface(iface)
    else:
        errors.append("iface unknown")
    _clear_ifb(ifb)
    if STATE_PATH.exists():
        try:
            STATE_PATH.unlink()
        except OSError as exc:
            errors.append(str(exc))
    return CommandResult(True, "REMOVED", "; ".join(errors), 0)


def _ensure_tools() -> CommandResult | None:
    missing = [t for t in ("tc", "ip") if shutil.which(t) is None]
    if missing:
        return CommandResult(
            False,
            "",
            f"Missing tools: {', '.join(missing)} — install iproute2",
            -1,
        )
    return None


def apply_throttle(settings: Settings) -> CommandResult:
    tools = _ensure_tools()
    if tools:
        return tools

    iface = default_iface()
    if not iface:
        return CommandResult(False, "", "Could not detect default network interface", -1)

    rate = settings.throttle_mbps()
    rate_str = f"{rate:.2f}mbit"

    # Reset previous shaping first.
    remove_throttle()

    # IFB for ingress (download) shaping — prevents download saturation.
    _run(["modprobe", "ifb", "numifbs=1"])
    if not _run_ok(["ip", "link", "show", "dev", IFB_NAME]):
        created = _run(["ip", "link", "add", "name", IFB_NAME, "type", "ifb"])
        if not created.ok and "File exists" not in (created.stderr or ""):
            # Fall back to ifb0 if custom name fails
            alt = "ifb0"
            _run(["modprobe", "ifb"])
            _run(["ip", "link", "set", "dev", alt, "up"])
            return _apply_with_ifb(iface, alt, rate, rate_str, settings)

    up = _run(["ip", "link", "set", "dev", IFB_NAME, "up"])
    if not up.ok:
        return CommandResult(False, up.stdout, up.stderr or "Failed to bring IFB up", up.code)

    return _apply_with_ifb(iface, IFB_NAME, rate, rate_str, settings)


def _apply_with_ifb(
    iface: str, ifb: str, rate: float, rate_str: str, settings: Settings
) -> CommandResult:
    _clear_iface(iface)
    _run(["tc", "qdisc", "del", "dev", ifb, "root"])

    # Egress — CAKE gaming-tuned (diffserv + ack-filter) when max_ping_mode
    cake_extra = (
        ["diffserv4", "ack-filter", "nat", "rtt", "80ms", "ethernet"]
        if settings.max_ping_mode
        else ["besteffort"]
    )
    eg = _run(
        [
            "tc",
            "qdisc",
            "replace",
            "dev",
            iface,
            "root",
            "cake",
            "bandwidth",
            rate_str,
            *cake_extra,
        ]
    )
    if not eg.ok:
        eg = _run(
            ["tc", "qdisc", "replace", "dev", iface, "root", "handle", "1:", "htb", "default", "10"]
        )
        if not eg.ok:
            return CommandResult(False, eg.stdout, eg.stderr or "Failed tc egress", eg.code)
        cls = _run(
            [
                "tc",
                "class",
                "add",
                "dev",
                iface,
                "parent",
                "1:",
                "classid",
                "1:10",
                "htb",
                "rate",
                rate_str,
                "ceil",
                rate_str,
            ]
        )
        if not cls.ok:
            return CommandResult(False, cls.stdout, cls.stderr, cls.code)
        _run(
            [
                "tc",
                "qdisc",
                "add",
                "dev",
                iface,
                "parent",
                "1:10",
                "fq_codel",
            ]
        )

    # Redirect ingress → IFB then shape download.
    ing = _run(["tc", "qdisc", "add", "dev", iface, "handle", "ffff:", "ingress"])
    if not ing.ok and "File exists" not in (ing.stderr or ""):
        return CommandResult(False, ing.stdout, ing.stderr or "Failed ingress qdisc", ing.code)

    filt = _run(
        [
            "tc",
            "filter",
            "add",
            "dev",
            iface,
            "parent",
            "ffff:",
            "protocol",
            "all",
            "u32",
            "match",
            "u32",
            "0",
            "0",
            "action",
            "mirred",
            "egress",
            "redirect",
            "dev",
            ifb,
        ]
    )
    if not filt.ok:
        return CommandResult(False, filt.stdout, filt.stderr or "Failed IFB redirect", filt.code)

    cake_in = _run(
        [
            "tc",
            "qdisc",
            "replace",
            "dev",
            ifb,
            "root",
            "cake",
            "bandwidth",
            rate_str,
            *cake_extra,
        ]
    )
    if not cake_in.ok:
        # police fallback on IFB via HTB
        htb = _run(
            ["tc", "qdisc", "replace", "dev", ifb, "root", "handle", "1:", "htb", "default", "10"]
        )
        if not htb.ok:
            return CommandResult(False, htb.stdout, cake_in.stderr or htb.stderr, htb.code)
        _run(
            [
                "tc",
                "class",
                "add",
                "dev",
                ifb,
                "parent",
                "1:",
                "classid",
                "1:10",
                "htb",
                "rate",
                rate_str,
                "ceil",
                rate_str,
            ]
        )
        _run(["tc", "qdisc", "add", "dev", ifb, "parent", "1:10", "fq_codel"])

    _save_state(iface, rate)
    dscp_note = ""
    if settings.mark_dscp:
        dscp_note = " (Linux: interface-level shaping via CAKE/HTB)"
    return CommandResult(
        True,
        f"APPLIED:{rate_str} iface={iface} ifb={ifb}{dscp_note}",
        "",
        0,
    )


def flush_dns() -> CommandResult:
    for cmd in (
        ["resolvectl", "flush-caches"],
        ["systemd-resolve", "--flush-caches"],
        ["nscd", "-i", "hosts"],
    ):
        if shutil.which(cmd[0]):
            result = _run(cmd)
            if result.ok:
                return CommandResult(True, "OK", "", 0)
    return CommandResult(True, "skip", "no dns flush tool", 0)
