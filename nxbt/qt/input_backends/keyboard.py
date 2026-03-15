from __future__ import annotations

from ..input_packets import clone_packet, create_input_packet, update_stick_positions
from ..models import InputProvider
from .base import BaseInputBackend


KEYBOARD_PROVIDER_ID = "keyboard"


class KeyboardInputBackend(BaseInputBackend):
    backend_id = "keyboard"
    KEYMAP = {
        "W": {"type": "stick_axis", "stick": "L_STICK", "flag": "LS_UP"},
        "A": {"type": "stick_axis", "stick": "L_STICK", "flag": "LS_LEFT"},
        "S": {"type": "stick_axis", "stick": "L_STICK", "flag": "LS_DOWN"},
        "D": {"type": "stick_axis", "stick": "L_STICK", "flag": "LS_RIGHT"},
        "UP": {"type": "stick_axis", "stick": "R_STICK", "flag": "RS_UP"},
        "LEFT": {"type": "stick_axis", "stick": "R_STICK", "flag": "RS_LEFT"},
        "DOWN": {"type": "stick_axis", "stick": "R_STICK", "flag": "RS_DOWN"},
        "RIGHT": {"type": "stick_axis", "stick": "R_STICK", "flag": "RS_RIGHT"},
        "T": {"type": "stick_press", "stick": "L_STICK"},
        "Y": {"type": "stick_press", "stick": "R_STICK"},
        "G": {"type": "button", "button": "DPAD_UP"},
        "V": {"type": "button", "button": "DPAD_LEFT"},
        "N": {"type": "button", "button": "DPAD_RIGHT"},
        "B": {"type": "button", "button": "DPAD_DOWN"},
        "[": {"type": "button", "button": "CAPTURE"},
        "]": {"type": "button", "button": "HOME"},
        "6": {"type": "button", "button": "PLUS"},
        "7": {"type": "button", "button": "MINUS"},
        "L": {"type": "button", "button": "A"},
        "K": {"type": "button", "button": "B"},
        "I": {"type": "button", "button": "X"},
        "J": {"type": "button", "button": "Y"},
        "1": {"type": "button", "button": "L"},
        "2": {"type": "button", "button": "ZL"},
        "8": {"type": "button", "button": "ZR"},
        "9": {"type": "button", "button": "R"},
    }

    def __init__(self):
        super().__init__()
        self._claimed_controller_index: int | None = None
        self._packet = create_input_packet()

    def list_providers(self) -> list[InputProvider]:
        return [
            InputProvider(
                backend_id=self.backend_id,
                provider_id=KEYBOARD_PROVIDER_ID,
                display_name="Keyboard",
            )
        ]

    def claim(self, provider_id: str, controller_index: int) -> None:
        if provider_id != KEYBOARD_PROVIDER_ID:
            raise ValueError("Unknown keyboard provider")
        self._claimed_controller_index = controller_index
        self._packet = create_input_packet()

    def release(self, provider_id: str, controller_index: int) -> None:
        if provider_id != KEYBOARD_PROVIDER_ID:
            return
        if self._claimed_controller_index == controller_index:
            self._claimed_controller_index = None
            self._packet = create_input_packet()

    def handle_key_press(self, token: str) -> bool:
        return self._set_key_state(token, True)

    def handle_key_release(self, token: str) -> bool:
        return self._set_key_state(token, False)

    def poll(self) -> dict[str, dict]:
        if self._claimed_controller_index is None:
            return {}
        update_stick_positions(self._packet)
        return {KEYBOARD_PROVIDER_ID: clone_packet(self._packet)}

    def _set_key_state(self, token: str, is_pressed: bool) -> bool:
        if self._claimed_controller_index is None:
            return False
        mapping = self.KEYMAP.get(token)
        if mapping is None:
            return False
        if mapping["type"] == "button":
            self._packet[mapping["button"]] = is_pressed
        elif mapping["type"] == "stick_press":
            self._packet[mapping["stick"]]["PRESSED"] = is_pressed
        else:
            self._packet[mapping["stick"]][mapping["flag"]] = is_pressed
        update_stick_positions(self._packet)
        return True
