from __future__ import annotations

from typing import Iterable

from ..backend import get_backend
from ..backend_base import BackendUnavailableError
from ..nxbt import Nxbt, PRO_CONTROLLER
from .input_packets import clone_packet, create_input_packet
from .models import ColorTuple, SessionRecord


class ControllerManager:
    def __init__(self, nx: Nxbt | None = None):
        self.nx = nx
        self.backend = get_backend()
        self.backend_status = self.backend.get_status()
        self._sessions: dict[int, SessionRecord] = {}
        self._available_adapters_cache = []
        self._startup_error = ""
        if self.nx is None:
            self._try_initialize_nxbt()
        else:
            self.backend_status = self.nx.get_backend_status()
            self._available_adapters_cache = list(self.nx.get_available_adapters())

    def shutdown(self) -> None:
        if self.nx is None:
            return
        try:
            self.nx._on_exit()
        except Exception:
            pass

    def list_sessions(self) -> list[SessionRecord]:
        return [self._sessions[index] for index in sorted(self._sessions)]

    def get_session(self, controller_index: int) -> SessionRecord | None:
        return self._sessions.get(controller_index)

    def refresh_available_adapters(self) -> list[str]:
        if self.nx is None:
            self._try_initialize_nxbt()
        if self.nx is None:
            self.backend_status = self.backend.get_status()
            self._available_adapters_cache = list(
                self.backend_status.get("available_adapters", [])
            )
            return list(self._available_adapters_cache)
        self.backend_status = self.nx.get_backend_status()
        self._available_adapters_cache = list(self.nx.get_available_adapters())
        return list(self._available_adapters_cache)

    def get_free_adapters(self, refresh: bool = False) -> list[str]:
        if refresh:
            self.refresh_available_adapters()
        used_adapters = {session.adapter_path for session in self._sessions.values()}
        return [
            adapter
            for adapter in self._available_adapters_cache
            if adapter not in used_adapters
        ]

    def get_saved_switch_addresses(self, adapter_path: str | None = None) -> list[str]:
        if self.nx is None:
            return list(self.backend.get_switch_addresses(adapter_path))
        return list(self.nx.get_switch_addresses(adapter_path))

    def get_saved_switch_addresses_by_adapter(
        self, adapters: list[str] | None = None
    ) -> dict[str, list[str]]:
        adapters = adapters or self.get_free_adapters()
        return {
            adapter: self.get_saved_switch_addresses(adapter)
            for adapter in adapters
        }

    def get_saved_switch_metadata(
        self, adapter_path: str, address: str
    ) -> dict | None:
        if self.nx is None:
            return self.backend.get_switch_metadata(adapter_path, address)
        return self.nx.get_switch_metadata(adapter_path, address)

    def get_saved_switch_metadata_by_adapter(
        self, adapters: list[str] | None = None
    ) -> dict[str, dict[str, dict]]:
        adapters = adapters or self.get_free_adapters()
        result = {}
        for adapter in adapters:
            adapter_metadata = {}
            for address in self.get_saved_switch_addresses(adapter):
                metadata = self.get_saved_switch_metadata(adapter, address)
                if metadata:
                    adapter_metadata[address] = metadata
            result[adapter] = adapter_metadata
        return result

    def forget_saved_switch(self, adapter_path: str, address: str) -> None:
        if self.nx is None:
            self.backend.forget_switch_pairing(adapter_path, address)
            return
        self.nx.forget_switch_pairing(adapter_path, address)

    def create_session(
        self,
        *,
        adapter_path: str,
        body_color: ColorTuple,
        button_color: ColorTuple,
        reconnect_target: str | list[str] | None,
    ) -> SessionRecord:
        nx = self._require_nx()
        controller_index = nx.create_controller(
            PRO_CONTROLLER,
            adapter_path=adapter_path,
            colour_body=list(body_color),
            colour_buttons=list(button_color),
            reconnect_address=reconnect_target,
        )
        session = SessionRecord(
            controller_index=controller_index,
            adapter_path=adapter_path,
            body_color=tuple(body_color),
            button_color=tuple(button_color),
            reconnect_target=reconnect_target,
        )
        self._sessions[controller_index] = session
        self.refresh_sessions()
        return session

    def remove_session(self, controller_index: int) -> None:
        nx = self._require_nx()
        self._sessions.pop(controller_index, None)
        nx.remove_controller(controller_index)

    def run_macro(self, controller_index: int, macro_text: str) -> str:
        nx = self._require_nx()
        macro_id = nx.macro(controller_index, macro_text, block=False)
        session = self._sessions[controller_index]
        session.current_macro_id = macro_id
        return macro_id

    def clear_macros(self, controller_index: int) -> None:
        nx = self._require_nx()
        nx.clear_macros(controller_index)
        session = self._sessions.get(controller_index)
        if session is not None:
            session.current_macro_id = None

    def send_input(self, controller_index: int, packet: dict) -> None:
        nx = self._require_nx()
        nx.set_controller_input(controller_index, packet)
        session = self._sessions.get(controller_index)
        if session is not None:
            session.last_input_packet = clone_packet(packet)

    def reset_input(self, controller_index: int) -> None:
        self.send_input(controller_index, create_input_packet())

    def refresh_sessions(self) -> list[SessionRecord]:
        if self.nx is None:
            return self.list_sessions()
        state = self.nx.state
        for controller_index, session in list(self._sessions.items()):
            if controller_index not in state:
                continue
            controller_state = state[controller_index]
            session.state = controller_state.get("state", session.state)
            session.errors = controller_state.get("errors", "")
            session.finished_macros = list(controller_state.get("finished_macros", []))
            if (
                session.current_macro_id is not None
                and session.current_macro_id in session.finished_macros
            ):
                session.current_macro_id = None
        return self.list_sessions()

    def update_provider_assignment(
        self, controller_index: int, provider_id: str | None
    ) -> None:
        session = self._sessions.get(controller_index)
        if session is not None:
            session.assigned_provider_id = provider_id

    def iter_session_indices(self) -> Iterable[int]:
        return self._sessions.keys()

    def _try_initialize_nxbt(self) -> None:
        self.backend_status = self.backend.get_status()
        if not self.backend_status.get("available", False):
            self._available_adapters_cache = list(
                self.backend_status.get("available_adapters", [])
            )
            self._startup_error = self.backend_status.get("message", "")
            return

        try:
            self.nx = Nxbt(disable_logging=True)
        except BackendUnavailableError as exc:
            self.nx = None
            self._startup_error = str(exc)
            self.backend_status = self.backend.get_status()
            self._available_adapters_cache = list(
                self.backend_status.get("available_adapters", [])
            )
            return

        self._startup_error = ""
        self.backend_status = self.nx.get_backend_status()
        self._available_adapters_cache = list(self.nx.get_available_adapters())

    def _require_nx(self) -> Nxbt:
        if self.nx is None:
            self._try_initialize_nxbt()
        if self.nx is None:
            message = self._startup_error or self.backend_status.get(
                "message",
                "The selected backend is not available.",
            )
            raise BackendUnavailableError(message)
        return self.nx
