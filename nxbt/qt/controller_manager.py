from __future__ import annotations

from typing import Iterable

from ..nxbt import Nxbt, PRO_CONTROLLER
from .input_packets import clone_packet, create_input_packet
from .models import ColorTuple, SessionRecord


class ControllerManager:
    def __init__(self, nx: Nxbt | None = None):
        self.nx = nx or Nxbt(disable_logging=True)
        self.backend_status = self.nx.get_backend_status()
        self._sessions: dict[int, SessionRecord] = {}
        self._available_adapters_cache = list(self.nx.get_available_adapters())

    def shutdown(self) -> None:
        try:
            self.nx._on_exit()
        except Exception:
            pass

    def list_sessions(self) -> list[SessionRecord]:
        return [self._sessions[index] for index in sorted(self._sessions)]

    def get_session(self, controller_index: int) -> SessionRecord | None:
        return self._sessions.get(controller_index)

    def refresh_available_adapters(self) -> list[str]:
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

    def get_saved_switch_addresses(self) -> list[str]:
        return list(self.nx.get_switch_addresses())

    def create_session(
        self,
        *,
        adapter_path: str,
        body_color: ColorTuple,
        button_color: ColorTuple,
        reconnect_target: str | list[str] | None,
    ) -> SessionRecord:
        controller_index = self.nx.create_controller(
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
        self._sessions.pop(controller_index, None)
        self.nx.remove_controller(controller_index)

    def run_macro(self, controller_index: int, macro_text: str) -> str:
        macro_id = self.nx.macro(controller_index, macro_text, block=False)
        session = self._sessions[controller_index]
        session.current_macro_id = macro_id
        return macro_id

    def clear_macros(self, controller_index: int) -> None:
        self.nx.clear_macros(controller_index)
        session = self._sessions.get(controller_index)
        if session is not None:
            session.current_macro_id = None

    def send_input(self, controller_index: int, packet: dict) -> None:
        self.nx.set_controller_input(controller_index, packet)
        session = self._sessions.get(controller_index)
        if session is not None:
            session.last_input_packet = clone_packet(packet)

    def reset_input(self, controller_index: int) -> None:
        self.send_input(controller_index, create_input_packet())

    def refresh_sessions(self) -> list[SessionRecord]:
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
