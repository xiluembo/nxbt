from __future__ import annotations

import importlib
import socket
import sys
from typing import Any

from .backend_base import BaseBackend, BackendUnavailableError


def _load_bluez_module():
    try:
        return importlib.import_module("nxbt.bluez")
    except ModuleNotFoundError as exc:
        raise BackendUnavailableError(
            "The linux BlueZ backend requires Linux-specific Bluetooth dependencies."
        ) from exc


class _LinuxL2CAPServerTransport:
    def __init__(self, address: str):
        self._s_ctrl = socket.socket(
            family=socket.AF_BLUETOOTH,
            type=socket.SOCK_SEQPACKET,
            proto=socket.BTPROTO_L2CAP,
        )
        self._s_itr = socket.socket(
            family=socket.AF_BLUETOOTH,
            type=socket.SOCK_SEQPACKET,
            proto=socket.BTPROTO_L2CAP,
        )

        try:
            self._s_ctrl.bind((address, 17))
            self._s_itr.bind((address, 19))
        except OSError:
            self._s_ctrl.bind((socket.BDADDR_ANY, 17))
            self._s_itr.bind((socket.BDADDR_ANY, 19))

        self._s_itr.listen(1)
        self._s_ctrl.listen(1)

    def accept(self):
        itr, _ = self._s_itr.accept()
        ctrl, _ = self._s_ctrl.accept()
        self.close()
        return itr, ctrl

    def close(self) -> None:
        for handle in (self._s_itr, self._s_ctrl):
            try:
                handle.close()
            except OSError:
                pass


class LinuxBlueZControllerAdapter:
    def __init__(self, adapter_path: str | None = None):
        bluez = _load_bluez_module()
        self._adapter = bluez.BlueZ(adapter_path=adapter_path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)

    def create_server_transport(self) -> _LinuxL2CAPServerTransport:
        return _LinuxL2CAPServerTransport(self.address)

    def create_reconnect_transport(self, reconnect_address):
        def recreate_sockets():
            ctrl = socket.socket(
                family=socket.AF_BLUETOOTH,
                type=socket.SOCK_SEQPACKET,
                proto=socket.BTPROTO_L2CAP,
            )
            itr = socket.socket(
                family=socket.AF_BLUETOOTH,
                type=socket.SOCK_SEQPACKET,
                proto=socket.BTPROTO_L2CAP,
            )
            return itr, ctrl

        itr = None
        ctrl = None
        if isinstance(reconnect_address, list):
            for address in reconnect_address:
                test_itr, test_ctrl = recreate_sockets()
                try:
                    test_ctrl.connect((address, 17))
                    test_itr.connect((address, 19))
                    itr = test_itr
                    ctrl = test_ctrl
                    break
                except OSError:
                    test_itr.close()
                    test_ctrl.close()
        elif isinstance(reconnect_address, str):
            test_itr, test_ctrl = recreate_sockets()
            test_ctrl.connect((reconnect_address, 17))
            test_itr.connect((reconnect_address, 19))
            itr = test_itr
            ctrl = test_ctrl

        if not itr or not ctrl:
            raise OSError(
                "Unable to reconnect to sockets at the given address(es)",
                reconnect_address,
            )

        return itr, ctrl

    def set_nonblocking(self, sock) -> None:
        sock.setblocking(False)

    def reset_address(self) -> None:
        return


class LinuxBlueZBackend(BaseBackend):
    name = "linux"

    def _ensure_supported(self) -> None:
        if not sys.platform.startswith("linux"):
            raise BackendUnavailableError(
                "The linux BlueZ backend is only supported on Linux."
            )

    def validate_runtime(self) -> None:
        self._ensure_supported()
        _load_bluez_module()

    def setup(self) -> None:
        self._ensure_supported()
        bluez = _load_bluez_module()
        bluez.toggle_clean_bluez(True)

    def cleanup(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        try:
            bluez = _load_bluez_module()
        except BackendUnavailableError:
            return
        bluez.toggle_clean_bluez(False)

    def get_available_adapters(self) -> list[str]:
        self._ensure_supported()
        bluez = _load_bluez_module()
        bus = bluez.dbus.SystemBus()
        try:
            return bluez.find_objects(bus, bluez.SERVICE_NAME, bluez.ADAPTER_INTERFACE)
        finally:
            bus.close()

    def get_switch_addresses(self, adapter_path: str | None = None) -> list[str]:
        self._ensure_supported()
        bluez = _load_bluez_module()
        return bluez.find_devices_by_alias("Nintendo Switch")

    def create_controller_adapter(
        self, adapter_path: str | None = None
    ) -> LinuxBlueZControllerAdapter:
        self._ensure_supported()
        return LinuxBlueZControllerAdapter(adapter_path=adapter_path)

    def forget_switch_pairing(self, adapter_path: str | None, address: str) -> None:
        self._ensure_supported()
        adapter = self.create_controller_adapter(adapter_path=adapter_path)
        adapter.remove_device(address)

    def get_status(self) -> dict[str, Any]:
        supported = sys.platform.startswith("linux")
        if not supported:
            return {
                "name": self.name,
                "supported": False,
                "available": False,
                "controller_transport_ready": True,
                "message": "BlueZ is only available on Linux.",
            }

        try:
            self.get_available_adapters()
        except BackendUnavailableError as exc:
            return {
                "name": self.name,
                "supported": True,
                "available": False,
                "controller_transport_ready": True,
                "message": str(exc),
            }
        except Exception as exc:  # pragma: no cover - depends on host bluetooth state
            return {
                "name": self.name,
                "supported": True,
                "available": False,
                "controller_transport_ready": True,
                "message": str(exc),
            }

        return {
            "name": self.name,
            "supported": True,
            "available": True,
            "controller_transport_ready": True,
            "message": "BlueZ backend ready.",
        }
