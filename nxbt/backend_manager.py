from __future__ import annotations

import os
import sys

from .backend_base import BaseBackend
from .backend_bumble import BumbleBackend
from .backend_linux_bluez import LinuxBlueZBackend


BACKEND_ENV_VAR = "NXBT_BACKEND"


def resolve_backend_name(requested: str | None = None) -> str:
    backend_name = requested or os.getenv(BACKEND_ENV_VAR) or "auto"

    if backend_name == "auto":
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform == "win32":
            return "bumble"
        return "bumble"

    if backend_name not in {"linux", "bumble"}:
        raise ValueError(f"Unknown nxbt backend '{backend_name}'")

    return backend_name


def get_backend(requested: str | None = None) -> BaseBackend:
    backend_name = resolve_backend_name(requested)

    if backend_name == "linux":
        return LinuxBlueZBackend()
    if backend_name == "bumble":
        return BumbleBackend()

    raise ValueError(f"Unknown nxbt backend '{backend_name}'")
