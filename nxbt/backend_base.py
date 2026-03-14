from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BackendUnavailableError(RuntimeError):
    """Raised when the selected backend cannot run in the current environment."""


class BaseBackend(ABC):
    name = "base"

    def validate_runtime(self) -> None:
        """Raise when the backend cannot be initialized on this machine."""

    def setup(self) -> None:
        """Prepare any global backend state before controller processes start."""

    def cleanup(self) -> None:
        """Revert any global backend state during shutdown."""

    @abstractmethod
    def get_available_adapters(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_switch_addresses(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def create_controller_adapter(self, adapter_path: str | None = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        raise NotImplementedError
