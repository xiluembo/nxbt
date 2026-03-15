from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .input_packets import create_input_packet


ColorTuple = tuple[int, int, int]


@dataclass(frozen=True)
class InputProvider:
    backend_id: str
    provider_id: str
    display_name: str
    profile_label: str = ""
    details: str = ""
    is_available: bool = True


@dataclass
class SessionRecord:
    controller_index: int
    adapter_path: str
    body_color: ColorTuple
    button_color: ColorTuple
    reconnect_target: str | list[str] | None
    assigned_provider_id: str | None = None
    state: str = "initializing"
    errors: str = ""
    current_macro_id: str | None = None
    finished_macros: list[str] = field(default_factory=list)
    last_input_packet: dict[str, Any] = field(default_factory=create_input_packet)
