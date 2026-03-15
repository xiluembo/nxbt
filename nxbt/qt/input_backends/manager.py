from __future__ import annotations

from dataclasses import replace

from ..models import InputProvider
from .keyboard import KEYBOARD_PROVIDER_ID, KeyboardInputBackend
from .pygame import PygameGamepadBackend


class InputBackendManager:
    def __init__(self, backends=None):
        self.backends = list(backends or [KeyboardInputBackend(), PygameGamepadBackend()])
        self._controller_provider_map: dict[int, str] = {}
        self._provider_controller_map: dict[str, int] = {}
        self._known_providers: dict[str, InputProvider] = {}
        self._provider_backend_map = {}
        self._current_providers: dict[str, InputProvider] = {}
        self._keyboard_backend = next(
            (
                backend
                for backend in self.backends
                if isinstance(backend, KeyboardInputBackend)
            ),
            None,
        )
        self.refresh_providers()

    def refresh_providers(self) -> list[InputProvider]:
        current_providers = {}
        current_backend_map = {}
        for backend in self.backends:
            for provider in backend.list_providers():
                current_providers[provider.provider_id] = provider
                current_backend_map[provider.provider_id] = backend
                self._known_providers[provider.provider_id] = provider
                self._provider_backend_map[provider.provider_id] = backend
        self._current_providers = current_providers
        self._provider_backend_map.update(current_backend_map)
        return list(current_providers.values())

    def get_warnings(self) -> list[str]:
        warnings = []
        for backend in self.backends:
            if backend.last_error:
                warnings.append(backend.last_error)
        return warnings

    def assigned_provider_id(self, controller_index: int) -> str | None:
        return self._controller_provider_map.get(controller_index)

    def list_assignable_providers(self, controller_index: int) -> list[InputProvider]:
        self.refresh_providers()
        providers = []
        for provider_id, provider in sorted(
            self._current_providers.items(),
            key=lambda item: (item[0] != KEYBOARD_PROVIDER_ID, item[1].display_name),
        ):
            owner = self._provider_controller_map.get(provider_id)
            if owner in (None, controller_index):
                providers.append(provider)

        current_provider_id = self._controller_provider_map.get(controller_index)
        if (
            current_provider_id is not None
            and current_provider_id not in self._current_providers
            and current_provider_id in self._known_providers
        ):
            providers.append(
                replace(
                    self._known_providers[current_provider_id],
                    display_name=(
                        f"{self._known_providers[current_provider_id].display_name} "
                        "(Unavailable)"
                    ),
                    is_available=False,
                )
            )

        return providers

    def assign_provider(self, controller_index: int, provider_id: str | None) -> None:
        if provider_id in (None, ""):
            self.release_controller(controller_index)
            return

        self.refresh_providers()
        owner = self._provider_controller_map.get(provider_id)
        if owner is not None and owner != controller_index:
            raise ValueError("That input provider is already assigned")

        provider = self._current_providers.get(provider_id)
        backend = self._provider_backend_map.get(provider_id)
        if provider is None or backend is None:
            raise ValueError("That input provider is not currently available")

        current_provider_id = self._controller_provider_map.get(controller_index)
        if current_provider_id == provider_id:
            return

        if current_provider_id is not None:
            self.release_controller(controller_index)

        backend.claim(provider_id, controller_index)
        self._controller_provider_map[controller_index] = provider_id
        self._provider_controller_map[provider_id] = controller_index

    def release_controller(self, controller_index: int) -> None:
        provider_id = self._controller_provider_map.pop(controller_index, None)
        if provider_id is None:
            return
        self._provider_controller_map.pop(provider_id, None)
        backend = self._provider_backend_map.get(provider_id)
        if backend is not None:
            backend.release(provider_id, controller_index)

    def poll_packets(self) -> dict[int, dict]:
        packets = {}
        for backend in self.backends:
            for provider_id, packet in backend.poll().items():
                controller_index = self._provider_controller_map.get(provider_id)
                if controller_index is not None:
                    packets[controller_index] = packet
        return packets

    def handle_key_press(self, token: str) -> bool:
        if self._keyboard_backend is None:
            return False
        return self._keyboard_backend.handle_key_press(token)

    def handle_key_release(self, token: str) -> bool:
        if self._keyboard_backend is None:
            return False
        return self._keyboard_backend.handle_key_release(token)

    def shutdown(self) -> None:
        for backend in self.backends:
            backend.shutdown()
