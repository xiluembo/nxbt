from __future__ import annotations

from ..input_packets import create_input_packet, normalize_axis
from ..models import InputProvider
from .base import BaseInputBackend


class PygameGamepadBackend(BaseInputBackend):
    backend_id = "pygame"
    XINPUT_NAME_TOKENS = ("xinput", "x-box", "xbox", "360", "one")

    def __init__(self):
        super().__init__()
        self._pygame = None
        self._claimed_provider_ids: set[str] = set()
        self._provider_joysticks: dict[str, object] = {}
        self._trigger_axis_modes: dict[str, dict[int, str]] = {}

    def list_providers(self) -> list[InputProvider]:
        pygame = self._ensure_pygame()
        if pygame is None:
            return []

        providers = []
        self._provider_joysticks = {}
        try:
            pygame.event.pump()
            for joystick_index in range(pygame.joystick.get_count()):
                joystick = pygame.joystick.Joystick(joystick_index)
                if not joystick.get_init():
                    joystick.init()
                instance_id = (
                    joystick.get_instance_id()
                    if hasattr(joystick, "get_instance_id")
                    else joystick_index
                )
                provider_id = f"gamepad:{instance_id}"
                provider_name = joystick.get_name() or f"Gamepad {joystick_index + 1}"
                providers.append(
                    InputProvider(
                        backend_id=self.backend_id,
                        provider_id=provider_id,
                        display_name=provider_name,
                    )
                )
                self._provider_joysticks[provider_id] = joystick
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"Pygame input backend failed: {exc}"
            return []
        return providers

    def claim(self, provider_id: str, controller_index: int) -> None:
        if provider_id not in {provider.provider_id for provider in self.list_providers()}:
            raise ValueError("Specified gamepad is unavailable")
        self._claimed_provider_ids.add(provider_id)

    def release(self, provider_id: str, controller_index: int) -> None:
        self._claimed_provider_ids.discard(provider_id)

    def poll(self) -> dict[str, dict]:
        pygame = self._ensure_pygame()
        if pygame is None or not self._claimed_provider_ids:
            return {}

        try:
            pygame.event.pump()
        except Exception as exc:
            self.last_error = f"Pygame input backend failed: {exc}"
            return {}

        packets = {}
        for provider_id in list(self._claimed_provider_ids):
            joystick = self._provider_joysticks.get(provider_id)
            if joystick is None:
                self.list_providers()
                joystick = self._provider_joysticks.get(provider_id)
            if joystick is None:
                continue
            packets[provider_id] = self._read_joystick_packet(provider_id, joystick)
        return packets

    def shutdown(self) -> None:
        if self._pygame is None:
            return
        try:
            self._pygame.joystick.quit()
            self._pygame.quit()
        except Exception:
            pass

    def _ensure_pygame(self):
        if self._pygame is not None:
            return self._pygame
        try:
            import pygame
        except ModuleNotFoundError:
            self.last_error = "Install pygame to enable joystick input."
            return None

        pygame.init()
        pygame.joystick.init()
        self._pygame = pygame
        self.last_error = ""
        return self._pygame

    def _read_joystick_packet(self, provider_id: str, joystick) -> dict:
        packet = create_input_packet()
        is_xinput = self._looks_like_xinput(joystick)

        packet["L_STICK"]["X_VALUE"] = normalize_axis(self._get_axis(joystick, 0))
        packet["L_STICK"]["Y_VALUE"] = normalize_axis(-self._get_axis(joystick, 1))
        packet["L_STICK"]["PRESSED"] = self._get_button(
            joystick, 8 if is_xinput else 10
        )

        packet["R_STICK"]["X_VALUE"] = normalize_axis(self._get_axis(joystick, 2))
        packet["R_STICK"]["Y_VALUE"] = normalize_axis(-self._get_axis(joystick, 3))
        packet["R_STICK"]["PRESSED"] = self._get_button(
            joystick, 9 if is_xinput else 11
        )

        packet["B"] = self._get_button(joystick, 0)
        packet["A"] = self._get_button(joystick, 1)
        packet["Y"] = self._get_button(joystick, 2)
        packet["X"] = self._get_button(joystick, 3)

        packet["L"] = self._get_button(joystick, 4)
        packet["R"] = self._get_button(joystick, 5)
        if is_xinput:
            packet["ZL"] = self._get_trigger_axis_pressed(provider_id, joystick, 4)
            packet["ZR"] = self._get_trigger_axis_pressed(provider_id, joystick, 5)
            packet["PLUS"] = self._get_button(joystick, 6)
            packet["MINUS"] = self._get_button(joystick, 7)
            packet["HOME"] = self._get_button(joystick, 10)
            packet["CAPTURE"] = False
        else:
            packet["ZL"] = self._get_button(joystick, 6)
            packet["ZR"] = self._get_button(joystick, 7)
            packet["PLUS"] = self._get_button(joystick, 8)
            packet["MINUS"] = self._get_button(joystick, 9)
            packet["HOME"] = self._get_button(joystick, 16)
            packet["CAPTURE"] = self._get_button(joystick, 17)

        if joystick.get_numhats() > 0:
            hat_x, hat_y = joystick.get_hat(0)
            packet["DPAD_UP"] = hat_y > 0
            packet["DPAD_DOWN"] = hat_y < 0
            packet["DPAD_LEFT"] = hat_x < 0
            packet["DPAD_RIGHT"] = hat_x > 0
        else:
            packet["DPAD_UP"] = self._get_button(joystick, 12)
            packet["DPAD_DOWN"] = self._get_button(joystick, 13)
            packet["DPAD_LEFT"] = self._get_button(joystick, 14)
            packet["DPAD_RIGHT"] = self._get_button(joystick, 15)

        return packet

    @staticmethod
    def _get_axis(joystick, index: int) -> float:
        if joystick.get_numaxes() <= index:
            return 0.0
        return float(joystick.get_axis(index))

    @staticmethod
    def _get_button(joystick, index: int) -> bool:
        if joystick.get_numbuttons() <= index:
            return False
        return bool(joystick.get_button(index))

    def _looks_like_xinput(self, joystick) -> bool:
        name = ""
        if hasattr(joystick, "get_name"):
            name = (joystick.get_name() or "").lower()
        if any(token in name for token in self.XINPUT_NAME_TOKENS):
            return True
        return joystick.get_numaxes() >= 6 and joystick.get_numbuttons() <= 11

    def _get_trigger_axis_pressed(self, provider_id: str, joystick, index: int) -> bool:
        if joystick.get_numaxes() <= index:
            return False
        raw_value = float(joystick.get_axis(index))
        mode = self._get_trigger_axis_mode(provider_id, index, raw_value)
        if mode == "signed":
            normalized_value = (raw_value + 1.0) / 2.0
        else:
            normalized_value = max(0.0, raw_value)
        normalized_value = max(0.0, min(1.0, normalized_value))
        return normalized_value >= 0.5

    def _get_trigger_axis_mode(
        self, provider_id: str, index: int, raw_value: float
    ) -> str:
        provider_modes = self._trigger_axis_modes.setdefault(provider_id, {})
        existing_mode = provider_modes.get(index)
        if raw_value < -0.5:
            provider_modes[index] = "signed"
            return "signed"
        if existing_mode is not None:
            return existing_mode
        provider_modes[index] = "unsigned"
        return "unsigned"
