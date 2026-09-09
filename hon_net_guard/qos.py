"""Cross-platform QoS / traffic shaping facade."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from .config import Settings


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    code: int


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_supported() -> bool:
    return is_windows() or is_linux()


def platform_name() -> str:
    if is_windows():
        return "Windows"
    if is_linux():
        return "Linux"
    return sys.platform


def is_admin() -> bool:
    if is_windows():
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    if is_linux():
        return os.geteuid() == 0
    return False


def apply_throttle(settings: Settings) -> CommandResult:
    if is_windows():
        from . import qos_windows as backend
    elif is_linux():
        from . import qos_linux as backend
    else:
        return CommandResult(False, "", f"Unsupported OS: {sys.platform}", -1)
    return backend.apply_throttle(settings)


def remove_throttle() -> CommandResult:
    if is_windows():
        from . import qos_windows as backend
    elif is_linux():
        from . import qos_linux as backend
    else:
        return CommandResult(False, "", f"Unsupported OS: {sys.platform}", -1)
    return backend.remove_throttle()


def throttle_active() -> bool:
    if is_windows():
        from . import qos_windows as backend
    elif is_linux():
        from . import qos_linux as backend
    else:
        return False
    return backend.throttle_active()


def tame_delivery_optimization() -> CommandResult:
    if is_windows():
        from . import qos_windows as backend

        return backend.tame_delivery_optimization()
    return CommandResult(True, "skip", "", 0)


def flush_dns() -> CommandResult:
    if is_windows():
        from . import qos_windows as backend

        return backend.flush_dns()
    if is_linux():
        from . import qos_linux as backend

        return backend.flush_dns()
    return CommandResult(False, "", "unsupported", -1)


# Back-compat aliases used by older stabilizer code paths
def remove_policy(name: str | None = None) -> CommandResult:
    return remove_throttle()


def list_existing_policies() -> list[str]:
    if throttle_active():
        return ["HoNNetGuardActive"]
    return []
