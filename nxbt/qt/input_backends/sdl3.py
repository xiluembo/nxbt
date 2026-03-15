from __future__ import annotations

import ctypes
import os
from pathlib import Path

from ..input_packets import create_input_packet, normalize_axis
from ..models import InputProvider
from .base import BaseInputBackend


SDL3_PROFILE_LABEL = "SDL3 Gamepad"
SDL3_RUNTIME_ENV = {
    "SDL_FIND_BINARIES": "1",
    "SDL_DOWNLOAD_BINARIES": "0",
    "SDL_CHECK_VERSION": "0",
    "SDL_LOG_LEVEL": "3",
}
SDL3_BINARY_NAMES = ("SDL3.dll", "SDL3d.dll")


class Sdl3GamepadBackend(BaseInputBackend):
    backend_id = "sdl3"

    def __init__(self):
        super().__init__()
        self._sdl3 = None
        self._initialized = False
        self._unavailable_reason = ""
        self._claimed_provider_ids: set[str] = set()
        self._provider_instance_ids: dict[str, int] = {}
        self._provider_names: dict[str, str] = {}
        self._open_gamepads: dict[str, object] = {}

    def list_providers(self) -> list[InputProvider]:
        sdl3 = self._ensure_sdl3()
        if sdl3 is None:
            return []

        providers = []
        self._provider_instance_ids = {}
        self._provider_names = {}
        try:
            self._pump_events()
            for instance_id in self._get_gamepad_ids():
                provider_id = self._provider_id(instance_id)
                provider_name = self._get_gamepad_name(instance_id)
                providers.append(
                    InputProvider(
                        backend_id=self.backend_id,
                        provider_id=provider_id,
                        display_name=provider_name,
                        profile_label=SDL3_PROFILE_LABEL,
                        details=(
                            f"Detected mapping: {SDL3_PROFILE_LABEL} | "
                            f"Name: {provider_name} | Instance ID: {instance_id}"
                        ),
                    )
                )
                self._provider_instance_ids[provider_id] = instance_id
                self._provider_names[provider_id] = provider_name
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"SDL3 gamepad backend failed: {exc}"
            return []
        return providers

    def claim(self, provider_id: str, controller_index: int) -> None:
        sdl3 = self._ensure_sdl3()
        if sdl3 is None:
            raise ValueError("SDL3 gamepad support is unavailable")

        if provider_id not in {provider.provider_id for provider in self.list_providers()}:
            raise ValueError("Specified SDL3 gamepad is unavailable")
        if provider_id in self._open_gamepads:
            self._claimed_provider_ids.add(provider_id)
            return

        instance_id = self._provider_instance_ids[provider_id]
        gamepad = sdl3.SDL_OpenGamepad(instance_id)
        if not gamepad:
            raise ValueError(self._format_sdl_error("Unable to open SDL3 gamepad"))

        self._open_gamepads[provider_id] = gamepad
        self._claimed_provider_ids.add(provider_id)

    def release(self, provider_id: str, controller_index: int) -> None:
        self._claimed_provider_ids.discard(provider_id)
        gamepad = self._open_gamepads.pop(provider_id, None)
        if gamepad is None or self._sdl3 is None:
            return
        try:
            self._sdl3.SDL_CloseGamepad(gamepad)
        except Exception:
            pass

    def poll(self) -> dict[str, dict]:
        sdl3 = self._ensure_sdl3()
        if sdl3 is None or not self._claimed_provider_ids:
            return {}

        try:
            self._pump_events()
        except Exception as exc:
            self.last_error = f"SDL3 gamepad backend failed: {exc}"
            return {}

        packets = {}
        for provider_id in list(self._claimed_provider_ids):
            gamepad = self._open_gamepads.get(provider_id)
            if gamepad is None:
                continue
            if hasattr(sdl3, "SDL_GamepadConnected") and not bool(
                sdl3.SDL_GamepadConnected(gamepad)
            ):
                self.release(provider_id, -1)
                continue
            packets[provider_id] = self._read_gamepad_packet(gamepad)
        return packets

    def shutdown(self) -> None:
        for provider_id in list(self._open_gamepads):
            self.release(provider_id, -1)
        if not self._initialized or self._sdl3 is None:
            return
        try:
            if hasattr(self._sdl3, "SDL_QuitSubSystem"):
                self._sdl3.SDL_QuitSubSystem(
                    self._sdl3.SDL_INIT_GAMEPAD | self._sdl3.SDL_INIT_EVENTS
                )
        except Exception:
            pass
        self._initialized = False

    def _ensure_sdl3(self):
        if self._unavailable_reason:
            self.last_error = self._unavailable_reason
            return None

        if self._sdl3 is None:
            for key, value in SDL3_RUNTIME_ENV.items():
                os.environ.setdefault(key, value)
            self._configure_local_runtime_path()
            try:
                import sdl3
            except ModuleNotFoundError:
                self._unavailable_reason = (
                    "Install PySDL3 and make the SDL3 runtime available on PATH "
                    "to enable gamepad input."
                )
                self.last_error = self._unavailable_reason
                return None
            self._sdl3 = sdl3

        if not self._has_runtime_binary():
            self._unavailable_reason = (
                "PySDL3 is installed, but no SDL3 runtime library was found. "
                "Install SDL3 and make the SDL3 DLL available on PATH."
            )
            self.last_error = self._unavailable_reason
            return None

        if not self._initialized:
            try:
                if hasattr(self._sdl3, "SDL_InitSubSystem"):
                    result = self._sdl3.SDL_InitSubSystem(
                        self._sdl3.SDL_INIT_GAMEPAD | self._sdl3.SDL_INIT_EVENTS
                    )
                else:
                    result = self._sdl3.SDL_Init(
                        self._sdl3.SDL_INIT_GAMEPAD | self._sdl3.SDL_INIT_EVENTS
                    )
            except Exception as exc:
                self._unavailable_reason = (
                    "Unable to initialize the SDL3 gamepad subsystem. "
                    f"{exc}"
                )
                self.last_error = self._unavailable_reason
                return None
            if not bool(result):
                self._unavailable_reason = self._format_sdl_error(
                    "Unable to initialize the SDL3 gamepad subsystem"
                )
                self.last_error = self._unavailable_reason
                return None
            self._initialized = True

        return self._sdl3

    def _configure_local_runtime_path(self) -> None:
        if os.environ.get("SDL_BINARY_PATH"):
            return

        runtime_dir = self._find_local_runtime_dir()
        if runtime_dir is None:
            return

        os.environ["SDL_BINARY_PATH"] = str(runtime_dir)
        os.environ.setdefault("SDL_DISABLE_METADATA", "1")

    def _find_local_runtime_dir(self) -> Path | None:
        candidate_dirs = []
        seen = set()
        for candidate in (
            Path.cwd(),
            Path(__file__).resolve().parents[3],
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            candidate_dirs.append(candidate)

        for directory in candidate_dirs:
            for binary_name in SDL3_BINARY_NAMES:
                if (directory / binary_name).exists():
                    return directory
        return None

    def _has_runtime_binary(self) -> bool:
        if self._sdl3 is None:
            return False
        if hasattr(self._sdl3, "SDL_GET_BINARY"):
            try:
                return self._sdl3.SDL_GET_BINARY("SDL3") is not None
            except Exception:
                return False
        binary_map = getattr(self._sdl3, "binaryMap", None)
        if isinstance(binary_map, dict):
            return bool(binary_map)
        return True

    def _get_gamepad_ids(self) -> list[int]:
        count = ctypes.c_int()
        ids = self._sdl3.SDL_GetGamepads(ctypes.byref(count))
        if ids is None:
            return []

        if isinstance(ids, (list, tuple)):
            return [int(instance_id) for instance_id in ids]

        result = []
        try:
            for index in range(count.value):
                result.append(int(ids[index]))
            return result
        finally:
            if hasattr(self._sdl3, "SDL_free"):
                self._sdl3.SDL_free(ids)

    def _get_gamepad_name(self, instance_id: int) -> str:
        raw_name = self._sdl3.SDL_GetGamepadNameForID(instance_id)
        if isinstance(raw_name, bytes):
            return raw_name.decode("utf-8", errors="replace")
        if raw_name is None:
            return f"Gamepad {instance_id}"
        return str(raw_name)

    def _pump_events(self) -> None:
        if hasattr(self._sdl3, "SDL_PumpEvents"):
            self._sdl3.SDL_PumpEvents()

    def _read_gamepad_packet(self, gamepad) -> dict:
        packet = create_input_packet()
        sdl3 = self._sdl3

        packet["L_STICK"]["X_VALUE"] = self._normalize_stick_axis(
            sdl3.SDL_GetGamepadAxis(gamepad, self._axis_constant("LEFTX"))
        )
        packet["L_STICK"]["Y_VALUE"] = self._normalize_stick_axis(
            -sdl3.SDL_GetGamepadAxis(gamepad, self._axis_constant("LEFTY"))
        )
        packet["R_STICK"]["X_VALUE"] = self._normalize_stick_axis(
            sdl3.SDL_GetGamepadAxis(gamepad, self._axis_constant("RIGHTX"))
        )
        packet["R_STICK"]["Y_VALUE"] = self._normalize_stick_axis(
            -sdl3.SDL_GetGamepadAxis(gamepad, self._axis_constant("RIGHTY"))
        )
        packet["L_STICK"]["PRESSED"] = self._gamepad_button(
            gamepad, self._button_constant("LEFT_STICK")
        )
        packet["R_STICK"]["PRESSED"] = self._gamepad_button(
            gamepad, self._button_constant("RIGHT_STICK")
        )

        packet["B"] = self._gamepad_button(gamepad, self._button_constant("SOUTH"))
        packet["A"] = self._gamepad_button(gamepad, self._button_constant("EAST"))
        packet["Y"] = self._gamepad_button(gamepad, self._button_constant("WEST"))
        packet["X"] = self._gamepad_button(gamepad, self._button_constant("NORTH"))

        packet["L"] = self._gamepad_button(
            gamepad, self._button_constant("LEFT_SHOULDER")
        )
        packet["R"] = self._gamepad_button(
            gamepad, self._button_constant("RIGHT_SHOULDER")
        )
        packet["ZL"] = self._trigger_pressed(
            sdl3.SDL_GetGamepadAxis(gamepad, self._axis_constant("LEFT_TRIGGER"))
        )
        packet["ZR"] = self._trigger_pressed(
            sdl3.SDL_GetGamepadAxis(gamepad, self._axis_constant("RIGHT_TRIGGER"))
        )
        packet["MINUS"] = self._gamepad_button(gamepad, self._button_constant("BACK"))
        packet["PLUS"] = self._gamepad_button(gamepad, self._button_constant("START"))
        packet["HOME"] = self._gamepad_button(gamepad, self._button_constant("GUIDE"))

        misc_button = self._button_constant("MISC1", required=False)
        touchpad_button = self._button_constant("TOUCHPAD", required=False)
        packet["CAPTURE"] = self._gamepad_button(
            gamepad, misc_button
        ) or self._gamepad_button(gamepad, touchpad_button)

        packet["DPAD_UP"] = self._gamepad_button(
            gamepad, self._button_constant("DPAD_UP")
        )
        packet["DPAD_DOWN"] = self._gamepad_button(
            gamepad, self._button_constant("DPAD_DOWN")
        )
        packet["DPAD_LEFT"] = self._gamepad_button(
            gamepad, self._button_constant("DPAD_LEFT")
        )
        packet["DPAD_RIGHT"] = self._gamepad_button(
            gamepad, self._button_constant("DPAD_RIGHT")
        )

        return packet

    def _axis_constant(self, name: str):
        for candidate in (
            f"SDL_GAMEPAD_AXIS_{name}",
            f"SDL_GAMEPAD_AXIS_{name.replace('_', '')}",
        ):
            if hasattr(self._sdl3, candidate):
                return getattr(self._sdl3, candidate)
        raise AttributeError(f"SDL3 axis constant not found for {name}")

    def _button_constant(self, name: str, *, required: bool = True):
        for candidate in (
            f"SDL_GAMEPAD_BUTTON_{name}",
            f"SDL_GAMEPAD_BUTTON_{name.replace('_', '')}",
        ):
            if hasattr(self._sdl3, candidate):
                return getattr(self._sdl3, candidate)
        if required:
            raise AttributeError(f"SDL3 button constant not found for {name}")
        return None

    def _gamepad_button(self, gamepad, button_constant) -> bool:
        if button_constant is None:
            return False
        return bool(self._sdl3.SDL_GetGamepadButton(gamepad, button_constant))

    def _format_sdl_error(self, prefix: str) -> str:
        if self._sdl3 is None or not hasattr(self._sdl3, "SDL_GetError"):
            return prefix
        error = self._sdl3.SDL_GetError()
        if isinstance(error, bytes):
            error = error.decode("utf-8", errors="replace")
        error_text = str(error).strip()
        if not error_text:
            return prefix
        return f"{prefix}: {error_text}"

    @staticmethod
    def _provider_id(instance_id: int) -> str:
        return f"gamepad:{instance_id}"

    @staticmethod
    def _normalize_stick_axis(value: int) -> int:
        if value >= 0:
            normalized = value / 32767.0 if value else 0.0
        else:
            normalized = value / 32768.0
        return normalize_axis(normalized)

    @staticmethod
    def _trigger_pressed(value: int) -> bool:
        normalized = max(0.0, min(1.0, value / 32767.0))
        return normalized >= 0.5
