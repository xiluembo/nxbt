from __future__ import annotations

import json
from typing import Any

from ..nxbt import DIRECT_INPUT_PACKET


def create_input_packet() -> dict[str, Any]:
    return json.loads(json.dumps(DIRECT_INPUT_PACKET))


def clone_packet(packet: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(packet))


def packets_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def update_stick_positions(packet: dict[str, Any]) -> dict[str, Any]:
    packet["L_STICK"]["X_VALUE"] = _axis_from_flags(
        negative=packet["L_STICK"]["LS_LEFT"],
        positive=packet["L_STICK"]["LS_RIGHT"],
    )
    packet["L_STICK"]["Y_VALUE"] = _axis_from_flags(
        negative=packet["L_STICK"]["LS_DOWN"],
        positive=packet["L_STICK"]["LS_UP"],
    )
    packet["R_STICK"]["X_VALUE"] = _axis_from_flags(
        negative=packet["R_STICK"]["RS_LEFT"],
        positive=packet["R_STICK"]["RS_RIGHT"],
    )
    packet["R_STICK"]["Y_VALUE"] = _axis_from_flags(
        negative=packet["R_STICK"]["RS_DOWN"],
        positive=packet["R_STICK"]["RS_UP"],
    )
    return packet


def normalize_axis(value: float, deadzone: float = 0.18) -> int:
    if abs(value) < deadzone:
        return 0
    value = max(-1.0, min(1.0, value))
    return int(round(value * 100))


def _axis_from_flags(*, negative: bool, positive: bool) -> int:
    if negative and not positive:
        return -100
    if positive and not negative:
        return 100
    return 0
