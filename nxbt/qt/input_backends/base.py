from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import InputProvider


class BaseInputBackend(ABC):
    backend_id = "base"

    def __init__(self):
        self.last_error = ""

    @abstractmethod
    def list_providers(self) -> list[InputProvider]:
        raise NotImplementedError

    @abstractmethod
    def claim(self, provider_id: str, controller_index: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def release(self, provider_id: str, controller_index: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def poll(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def shutdown(self) -> None:
        return
