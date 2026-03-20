from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

from ..input_packets import create_input_packet, normalize_axis
from ..models import InputProvider
from ..motion import (
    MOTION_STATUS_DEFAULT,
    MOTION_STATUS_SENSOR,
    MotionBuffer,
    motion_details,
)
from .base import BaseInputBackend


SDL3_PROFILE_LABEL = "SDL3 Gamepad"
SDL3_RUNTIME_ENV = {
    "SDL_FIND_BINARIES": "1",
    "SDL_DOWNLOAD_BINARIES": "0",
    "SDL_CHECK_VERSION": "0",
    "SDL_LOG_LEVEL": "3",
}
SDL3_BINARY_NAMES = ("SDL3.dll", "SDL3d.dll")


@dataclass
class _ProviderMotionState:
    buffer: MotionBuffer
    accelerometer_sensor: int | None = None
    gyroscope_sensor: int | None = None


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
        self._motion_states: dict[str, _ProviderMotionState] = {}
        self._init_flags = 0

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
                motion_state = self._motion_states.get(provider_id)
                motion_status = MOTION_STATUS_DEFAULT
                motion_available = False
                status_detail = "Motion sensor status is checked after assignment."
                if motion_state is not None:
                    motion_status = motion_state.buffer.motion_status
                    motion_available = motion_state.buffer.motion_available
                    status_detail = motion_state.buffer.status_detail
                providers.append(
                    InputProvider(
                        backend_id=self.backend_id,
                        provider_id=provider_id,
                        display_name=provider_name,
                        profile_label=SDL3_PROFILE_LABEL,
                        details=motion_details(
                            provider_name=provider_name,
                            instance_id=instance_id,
                            motion_status=motion_status,
                            status_detail=status_detail,
                        ),
                        motion_status=motion_status,
                        motion_available=motion_available,
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
        self._motion_states[provider_id] = self._configure_motion_state(gamepad)
        self._claimed_provider_ids.add(provider_id)

    def release(self, provider_id: str, controller_index: int) -> None:
        self._claimed_provider_ids.discard(provider_id)
        gamepad = self._open_gamepads.pop(provider_id, None)
        self._motion_states.pop(provider_id, None)
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
            packets[provider_id] = self._read_gamepad_packet(provider_id, gamepad)
        return packets

    def shutdown(self) -> None:
        for provider_id in list(self._open_gamepads):
            self.release(provider_id, -1)
        if not self._initialized or self._sdl3 is None:
            return
        try:
            if hasattr(self._sdl3, "SDL_QuitSubSystem"):
                self._sdl3.SDL_QuitSubSystem(self._init_flags)
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
            self._init_flags = self._sdl3.SDL_INIT_GAMEPAD | self._sdl3.SDL_INIT_EVENTS
            if hasattr(self._sdl3, "SDL_INIT_SENSOR"):
                self._init_flags |= self._sdl3.SDL_INIT_SENSOR
            try:
                if hasattr(self._sdl3, "SDL_InitSubSystem"):
                    result = self._sdl3.SDL_InitSubSystem(self._init_flags)
                else:
                    result = self._sdl3.SDL_Init(self._init_flags)
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

    def _read_gamepad_packet(self, provider_id: str, gamepad) -> dict:
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
        packet["IMU_DATA"] = self._build_motion_report(provider_id, gamepad)

        return packet

    def _configure_motion_state(self, gamepad) -> _ProviderMotionState:
        motion_state = _ProviderMotionState(buffer=MotionBuffer())
        sdl3 = self._sdl3
        if sdl3 is None or not hasattr(sdl3, "SDL_GamepadHasSensor"):
            motion_state.buffer.status_detail = "SDL3 sensor APIs are unavailable."
            return motion_state

        accelerometer_sensor = getattr(sdl3, "SDL_SENSOR_ACCEL", None)
        gyroscope_sensor = getattr(sdl3, "SDL_SENSOR_GYRO", None)
        if accelerometer_sensor is None or gyroscope_sensor is None:
            motion_state.buffer.status_detail = "Required SDL3 motion sensors are unavailable."
            return motion_state

        if not bool(sdl3.SDL_GamepadHasSensor(gamepad, accelerometer_sensor)) or not bool(
            sdl3.SDL_GamepadHasSensor(gamepad, gyroscope_sensor)
        ):
            motion_state.buffer.status_detail = (
                "No compatible motion sensors detected on this controller."
            )
            return motion_state

        if not self._enable_sensor(gamepad, accelerometer_sensor) or not self._enable_sensor(
            gamepad, gyroscope_sensor
        ):
            motion_state.buffer.status_detail = (
                "Unable to enable motion sensors; using default IMU."
            )
            return motion_state

        motion_state.accelerometer_sensor = accelerometer_sensor
        motion_state.gyroscope_sensor = gyroscope_sensor
        motion_state.buffer.motion_available = True
        motion_state.buffer.motion_status = MOTION_STATUS_SENSOR
        motion_state.buffer.status_detail = "Using accelerometer and gyroscope."
        return motion_state

    def _enable_sensor(self, gamepad, sensor_type: int) -> bool:
        sdl3 = self._sdl3
        if sdl3 is None or not hasattr(sdl3, "SDL_SetGamepadSensorEnabled"):
            return False

        try:
            if hasattr(sdl3, "SDL_GamepadSensorEnabled") and bool(
                sdl3.SDL_GamepadSensorEnabled(gamepad, sensor_type)
            ):
                return True
            return bool(sdl3.SDL_SetGamepadSensorEnabled(gamepad, sensor_type, True))
        except Exception:
            return False

    def _build_motion_report(self, provider_id: str, gamepad) -> list[int]:
        motion_state = self._motion_states.get(provider_id)
        if motion_state is None:
            return MotionBuffer().build_report()

        if (
            not motion_state.buffer.motion_available
            or motion_state.accelerometer_sensor is None
            or motion_state.gyroscope_sensor is None
        ):
            return motion_state.buffer.build_report()

        accelerometer_values = self._read_sensor_data(
            gamepad, motion_state.accelerometer_sensor
        )
        gyroscope_values = self._read_sensor_data(
            gamepad, motion_state.gyroscope_sensor
        )
        if accelerometer_values is None or gyroscope_values is None:
            motion_state.buffer.motion_available = False
            motion_state.buffer.motion_status = MOTION_STATUS_DEFAULT
            motion_state.buffer.status_detail = "Motion sensor read failed."
            motion_state.buffer.samples.clear()
            return motion_state.buffer.build_report()

        motion_state.buffer.push_sensor_sample(
            accelerometer_values,
            gyroscope_values,
        )
        return motion_state.buffer.build_report()

    def _read_sensor_data(self, gamepad, sensor_type: int) -> tuple[float, float, float] | None:
        sdl3 = self._sdl3
        if sdl3 is None or not hasattr(sdl3, "SDL_GetGamepadSensorData"):
            return None

        buffer = (ctypes.c_float * 3)()
        try:
            success = sdl3.SDL_GetGamepadSensorData(gamepad, sensor_type, buffer, 3)
        except Exception:
            return None
        if not bool(success):
            return None
        return (float(buffer[0]), float(buffer[1]), float(buffer[2]))

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
