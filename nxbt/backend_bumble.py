from __future__ import annotations

import asyncio
import importlib
import json
import os
import queue
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .backend_base import BaseBackend, BackendUnavailableError


DEFAULT_TRANSPORT = "usb:0"
DEFAULT_ALIAS = "Pro Controller"
DEFAULT_CLASS_OF_DEVICE = 0x002508
DEFAULT_SERVICE_RECORD_HANDLE = 0x00010001
CLASSIC_CONNECT_TIMEOUT = 12.0
CLASSIC_AUTH_TIMEOUT = 8.0
CLASSIC_ENCRYPT_TIMEOUT = 8.0
CLASSIC_L2CAP_TIMEOUT = 8.0
TRANSPORT_ENV_VAR = "NXBT_BUMBLE_TRANSPORT"
KEYSTORE_ENV_VAR = "NXBT_BUMBLE_KEYSTORE"
FIRMWARE_ENV_VAR = "BUMBLE_RTK_FIRMWARE_DIR"
_CLOSE_SENTINEL = object()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_dir() -> Path:
    return _repo_root() / ".bumble-state"


def _firmware_dir() -> Path:
    return Path(os.environ.get(FIRMWARE_ENV_VAR) or (_repo_root() / ".bumble-firmware"))


def _keystore_path() -> Path:
    configured = os.environ.get(KEYSTORE_ENV_VAR)
    if configured:
        return Path(configured)
    return _state_dir() / "keys.json"


def _default_transport() -> str:
    return os.environ.get(TRANSPORT_ENV_VAR, DEFAULT_TRANSPORT)


def _parse_device_class(device_class: str | int) -> int:
    if isinstance(device_class, int):
        return device_class
    return int(str(device_class), 16)


def _address_to_string(address: Any) -> str:
    if hasattr(address, "to_string"):
        return address.to_string(False)
    return str(address).split("/", 1)[0]


def _load_bumble_modules() -> dict[str, Any]:
    try:
        device = importlib.import_module("bumble.device")
        hci = importlib.import_module("bumble.hci")
        hid = importlib.import_module("bumble.hid")
        keys = importlib.import_module("bumble.keys")
        sdp = importlib.import_module("bumble.sdp")
        transport = importlib.import_module("bumble.transport")
        core = importlib.import_module("bumble.core")
    except ModuleNotFoundError as exc:
        raise BackendUnavailableError(
            "The Bumble backend requires the optional 'bumble' dependency."
        ) from exc

    return {
        "Device": device.Device,
        "DeviceConfiguration": device.DeviceConfiguration,
        "JsonKeyStore": keys.JsonKeyStore,
        "HidDevice": hid.Device,
        "HidControlPsm": hid.HID_CONTROL_PSM,
        "HidInterruptPsm": hid.HID_INTERRUPT_PSM,
        "HCI_Write_Local_Name_Command": hci.HCI_Write_Local_Name_Command,
        "HCI_Write_Class_Of_Device_Command": hci.HCI_Write_Class_Of_Device_Command,
        "Address": hci.Address,
        "UUID": core.UUID,
        "DataElement": sdp.DataElement,
        "ServiceAttribute": sdp.ServiceAttribute,
        "open_transport": transport.open_transport,
    }


def _load_usb_modules() -> dict[str, Any]:
    try:
        transport_usb = importlib.import_module("bumble.transport.usb")
        usb1 = importlib.import_module("usb1")
    except ModuleNotFoundError as exc:
        raise BackendUnavailableError(
            "USB adapter discovery requires Bumble's USB transport dependencies."
        ) from exc

    return {"load_libusb": transport_usb.load_libusb, "usb1": usb1}


def _parse_sdp_element(element: ET.Element, modules: dict[str, Any]):
    data_element = modules["DataElement"]
    uuid_type = modules["UUID"]
    tag = element.tag

    if tag == "sequence":
        return data_element.sequence(
            [_parse_sdp_element(child, modules) for child in list(element)]
        )
    if tag == "uuid":
        value = element.attrib["value"]
        if value.startswith("0x"):
            numeric_value = int(value, 16)
            if numeric_value <= 0xFFFF:
                uuid_value = uuid_type.from_16_bits(numeric_value)
            else:
                uuid_value = uuid_type.from_32_bits(numeric_value)
        else:
            uuid_value = uuid_type(value)
        return data_element.uuid(uuid_value)
    if tag == "uint8":
        return data_element.unsigned_integer_8(int(element.attrib["value"], 16))
    if tag == "uint16":
        return data_element.unsigned_integer_16(int(element.attrib["value"], 16))
    if tag == "uint32":
        return data_element.unsigned_integer_32(int(element.attrib["value"], 16))
    if tag == "boolean":
        return data_element.boolean(element.attrib["value"].lower() == "true")
    if tag == "text":
        value = element.attrib["value"]
        if element.attrib.get("encoding") == "hex":
            return data_element.text_string(bytes.fromhex(value))
        return data_element.text_string(value.encode("utf-8"))

    raise ValueError(f"Unsupported SDP XML element '{tag}'")


def _parse_sdp_record(record_xml: str, modules: dict[str, Any]) -> dict[int, list[Any]]:
    service_attribute = modules["ServiceAttribute"]
    data_element = modules["DataElement"]

    root = ET.fromstring(record_xml)
    attributes = []
    has_service_record_handle = False

    for attribute in root.findall("attribute"):
        attribute_id = int(attribute.attrib["id"], 16)
        value_node = next(iter(attribute), None)
        if value_node is None:
            continue
        if attribute_id == 0x0000:
            has_service_record_handle = True
        attributes.append(
            service_attribute(attribute_id, _parse_sdp_element(value_node, modules))
        )

    if not has_service_record_handle:
        attributes.insert(
            0,
            service_attribute(
                0x0000, data_element.unsigned_integer_32(DEFAULT_SERVICE_RECORD_HANDLE)
            ),
        )

    return {DEFAULT_SERVICE_RECORD_HANDLE: attributes}


class _NxbtHidDevice:
    EVENT_BT_CONNECTION = "nxbt_connection"
    EVENT_BT_DISCONNECTION = "nxbt_disconnection"
    EVENT_L2CAP_CHANNEL_OPEN = "nxbt_l2cap_channel_open"
    EVENT_L2CAP_CHANNEL_CLOSE = "nxbt_l2cap_channel_close"

    def __new__(cls, device):
        modules = _load_bumble_modules()
        base_cls = modules["HidDevice"]

        class NxbtHidDevice(base_cls):
            def on_device_connection(self, connection) -> None:
                super().on_device_connection(connection)
                self.emit(cls.EVENT_BT_CONNECTION, connection)

            def on_device_disconnection(self, reason: int) -> None:
                super().on_device_disconnection(reason)
                self.emit(cls.EVENT_BT_DISCONNECTION, reason)

            def on_l2cap_channel_open(self, l2cap_channel) -> None:
                super().on_l2cap_channel_open(l2cap_channel)
                self.emit(cls.EVENT_L2CAP_CHANNEL_OPEN, l2cap_channel)

            def on_l2cap_channel_close(self, l2cap_channel) -> None:
                super().on_l2cap_channel_close(l2cap_channel)
                self.emit(cls.EVENT_L2CAP_CHANNEL_CLOSE, l2cap_channel)

        return NxbtHidDevice(device)


class _BumbleSocket:
    def __init__(self, runtime: "_BumbleRuntime", channel: str, peer_address: str):
        self.runtime = runtime
        self.channel = channel
        self.peer_address = peer_address
        self._incoming: queue.Queue[bytes | object] = queue.Queue()
        self._blocking = True
        self._closed = False

    def feed(self, data: bytes) -> None:
        if self._closed:
            return
        self._incoming.put_nowait(data)

    def close_from_remote(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._incoming.put_nowait(_CLOSE_SENTINEL)

    def setblocking(self, blocking: bool) -> None:
        self._blocking = blocking

    def recv(self, _bufsize: int) -> bytes:
        if self._blocking:
            item = self._incoming.get()
        else:
            try:
                item = self._incoming.get_nowait()
            except queue.Empty as exc:
                raise BlockingIOError() from exc

        if item is _CLOSE_SENTINEL:
            return b""
        return item

    def sendall(self, data: bytes) -> None:
        if self._closed:
            raise OSError("Bluetooth channel closed")
        self.runtime.send_pdu(self.channel, data)

    def getpeername(self):
        return (self.peer_address, 0)

    def getsockname(self):
        return (self.runtime.address, 0)


class _BumbleConnectionPair:
    def __init__(self, runtime: "_BumbleRuntime", peer_address: str):
        self.runtime = runtime
        self.peer_address = peer_address
        self.control = _BumbleSocket(runtime, "control", peer_address)
        self.interrupt = _BumbleSocket(runtime, "interrupt", peer_address)
        self._control_open = False
        self._interrupt_open = False
        self.ready = runtime.loop.create_future()

    def mark_channel_open(self, psm: int) -> None:
        if psm == self.runtime.hid_control_psm:
            self._control_open = True
        elif psm == self.runtime.hid_interrupt_psm:
            self._interrupt_open = True

        if (
            self._control_open
            and self._interrupt_open
            and not self.ready.done()
        ):
            self.ready.set_result((self.interrupt, self.control))

    def close(self) -> None:
        self.control.close_from_remote()
        self.interrupt.close_from_remote()
        if not self.ready.done():
            self.ready.set_exception(OSError("Bluetooth connection closed"))


class _BumbleRuntime:
    def __init__(
        self,
        transport_spec: str,
        alias: str,
        class_of_device: int,
        discoverable: bool,
        connectable: bool,
        sdp_record_xml: str | None,
    ):
        self.transport_spec = transport_spec
        self.alias = alias
        self.class_of_device = class_of_device
        self.discoverable = discoverable
        self.connectable = connectable
        self.sdp_record_xml = sdp_record_xml
        self.firmware_dir = _firmware_dir()
        self.keystore_path = _keystore_path()
        self.address = "00:00:00:00:00:00"
        self.loop = asyncio.new_event_loop()
        self.thread: threading.Thread | None = None
        self.transport = None
        self.device = None
        self.hid_device = None
        self.hid_control_psm = 0x0011
        self.hid_interrupt_psm = 0x0013
        self.connections: dict[str, Any] = {}
        self.current_session: _BumbleConnectionPair | None = None
        self._startup_done = threading.Event()
        self._running = False

    def _loop_main(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._startup_done.set()
        self.loop.run_forever()

    def start(self) -> None:
        if self._running:
            return

        self.thread = threading.Thread(target=self._loop_main, daemon=True)
        self.thread.start()
        self._startup_done.wait()
        try:
            self.call(self._async_start())
        except Exception:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=10)
            self.thread = None
            raise
        self._running = True

    def stop(self) -> None:
        if not self.thread:
            return

        try:
            self.call(self._async_stop(), timeout=10)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=10)
            self.thread = None
            self._running = False

    def call(self, coroutine, timeout: float | None = None):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result(timeout)

    async def _async_start(self) -> None:
        if self.transport is not None:
            return

        modules = _load_bumble_modules()
        if (
            FIRMWARE_ENV_VAR not in os.environ
            and self.firmware_dir.exists()
        ):
            os.environ[FIRMWARE_ENV_VAR] = str(self.firmware_dir)

        state_dir = self.keystore_path.parent
        state_dir.mkdir(parents=True, exist_ok=True)

        device_config = modules["DeviceConfiguration"](
            name=self.alias,
            class_of_device=self.class_of_device,
            classic_enabled=True,
            classic_accept_any=True,
            le_enabled=False,
            connectable=self.connectable,
            discoverable=self.discoverable,
        )

        self.transport = await modules["open_transport"](self.transport_spec)
        self.device = modules["Device"].from_config_with_hci(
            device_config, self.transport.source, self.transport.sink
        )
        self.hid_device = _NxbtHidDevice(self.device)
        self.hid_control_psm = modules["HidControlPsm"]
        self.hid_interrupt_psm = modules["HidInterruptPsm"]
        self.hid_device.on(self.hid_device.EVENT_INTERRUPT_DATA, self._on_interrupt_data)
        self.hid_device.on(self.hid_device.EVENT_CONTROL_DATA, self._on_control_data)
        self.hid_device.on(
            _NxbtHidDevice.EVENT_BT_CONNECTION, self._on_connection
        )
        self.hid_device.on(
            _NxbtHidDevice.EVENT_BT_DISCONNECTION, self._on_disconnection
        )
        self.hid_device.on(
            _NxbtHidDevice.EVENT_L2CAP_CHANNEL_OPEN, self._on_l2cap_channel_open
        )
        self.hid_device.on(
            _NxbtHidDevice.EVENT_L2CAP_CHANNEL_CLOSE, self._on_l2cap_channel_close
        )

        if self.sdp_record_xml:
            self.device.sdp_service_records = _parse_sdp_record(
                self.sdp_record_xml, modules
            )

        await self.device.power_on()
        self.device.keystore = modules["JsonKeyStore"].from_device(
            self.device, filename=str(self.keystore_path)
        )
        await self._apply_identity()
        await self.device.set_connectable(self.connectable)
        await self.device.set_discoverable(self.discoverable)

    async def _async_stop(self) -> None:
        if self.current_session:
            self.current_session.close()
            self.current_session = None

        if self.device is not None:
            for connection in list(self.connections.values()):
                try:
                    await connection.disconnect()
                except Exception:
                    pass

        self.connections.clear()

        if self.transport is not None:
            await self.transport.close()
            self.transport = None

        self.device = None
        self.hid_device = None

    async def _apply_identity(self) -> None:
        if self.device is None:
            return

        modules = _load_bumble_modules()
        self.device.name = self.alias
        self.device.class_of_device = self.class_of_device
        await self.device.send_sync_command_raw(
            modules["HCI_Write_Local_Name_Command"](
                local_name=self.alias.encode("utf-8")
            )
        )
        await self.device.send_sync_command_raw(
            modules["HCI_Write_Class_Of_Device_Command"](
                class_of_device=self.class_of_device
            )
        )
        self.address = _address_to_string(self.device.public_address)

    def _prepare_session(self, connection) -> _BumbleConnectionPair:
        if self.current_session is not None:
            self.current_session.close()

        session = _BumbleConnectionPair(self, _address_to_string(connection.peer_address))
        self.current_session = session

        if self.hid_device and self.hid_device.l2cap_ctrl_channel is not None:
            session.mark_channel_open(self.hid_device.l2cap_ctrl_channel.psm)
        if self.hid_device and self.hid_device.l2cap_intr_channel is not None:
            session.mark_channel_open(self.hid_device.l2cap_intr_channel.psm)

        return session

    async def accept(self):
        await self._async_start()
        assert self.device is not None
        connection = await self.device.accept()
        session = self._prepare_session(connection)
        return await session.ready

    async def reconnect(self, reconnect_address: str):
        await self._async_start()
        assert self.device is not None
        assert self.hid_device is not None

        connection = await asyncio.wait_for(
            self.device.connect_classic(reconnect_address),
            timeout=CLASSIC_CONNECT_TIMEOUT,
        )
        if not connection.authenticated:
            await asyncio.wait_for(
                connection.authenticate(),
                timeout=CLASSIC_AUTH_TIMEOUT,
            )
        if not connection.encryption:
            await asyncio.wait_for(
                connection.encrypt(),
                timeout=CLASSIC_ENCRYPT_TIMEOUT,
            )
        session = self._prepare_session(connection)
        await asyncio.wait_for(
            self.hid_device.connect_control_channel(),
            timeout=CLASSIC_L2CAP_TIMEOUT,
        )
        await asyncio.wait_for(
            self.hid_device.connect_interrupt_channel(),
            timeout=CLASSIC_L2CAP_TIMEOUT,
        )
        if self.hid_device.l2cap_ctrl_channel is not None:
            session.mark_channel_open(self.hid_device.l2cap_ctrl_channel.psm)
        if self.hid_device.l2cap_intr_channel is not None:
            session.mark_channel_open(self.hid_device.l2cap_intr_channel.psm)
        return await asyncio.wait_for(session.ready, timeout=CLASSIC_L2CAP_TIMEOUT)

    async def set_discoverable(self, discoverable: bool) -> None:
        self.discoverable = discoverable
        await self._async_start()
        assert self.device is not None
        await self.device.set_discoverable(discoverable)

    async def set_connectable(self, connectable: bool) -> None:
        self.connectable = connectable
        await self._async_start()
        assert self.device is not None
        await self.device.set_connectable(connectable)

    async def set_alias(self, alias: str) -> None:
        self.alias = alias
        await self._async_start()
        await self._apply_identity()

    async def set_class(self, class_of_device: int) -> None:
        self.class_of_device = class_of_device
        await self._async_start()
        await self._apply_identity()

    async def update_sdp(self, sdp_record_xml: str) -> None:
        self.sdp_record_xml = sdp_record_xml
        await self._async_start()
        assert self.device is not None
        self.device.sdp_service_records = _parse_sdp_record(
            sdp_record_xml, _load_bumble_modules()
        )

    async def disconnect_peer(self, peer_address: str) -> None:
        connection = self.connections.get(peer_address)
        if connection is None:
            return
        await connection.disconnect()

    def send_pdu(self, channel: str, data: bytes) -> None:
        async def sender() -> None:
            if self.hid_device is None:
                raise OSError("Bumble HID device is not initialized")

            if channel == "interrupt":
                if self.hid_device.l2cap_intr_channel is None:
                    raise OSError("Interrupt channel is not connected")
                self.hid_device.send_pdu_on_intr(data)
                return

            if self.hid_device.l2cap_ctrl_channel is None:
                raise OSError("Control channel is not connected")
            self.hid_device.send_pdu_on_ctrl(data)

        self.call(sender())

    def _on_connection(self, connection) -> None:
        peer_address = _address_to_string(connection.peer_address)
        self.connections[peer_address] = connection
        self.address = _address_to_string(connection.self_address)

    def _on_disconnection(self, _reason: int) -> None:
        self.connections.clear()
        if self.current_session is not None:
            self.current_session.close()
            self.current_session = None

    def _on_l2cap_channel_open(self, channel) -> None:
        if self.current_session is None:
            return
        self.current_session.mark_channel_open(channel.psm)

    def _on_l2cap_channel_close(self, channel) -> None:
        if self.current_session is None:
            return
        if channel.psm == self.hid_control_psm:
            self.current_session.control.close_from_remote()
        elif channel.psm == self.hid_interrupt_psm:
            self.current_session.interrupt.close_from_remote()

    def _on_interrupt_data(self, pdu: bytes) -> None:
        if self.current_session is None:
            return
        self.current_session.interrupt.feed(pdu)

    def _on_control_data(self, pdu: bytes) -> None:
        if self.current_session is None:
            return
        self.current_session.control.feed(pdu)


class _BumbleServerTransport:
    def __init__(self, runtime: _BumbleRuntime):
        self.runtime = runtime

    def accept(self):
        return self.runtime.call(self.runtime.accept())

    def close(self) -> None:
        self.runtime.stop()


class BumbleControllerAdapter:
    def __init__(self, adapter_path: str | None = None):
        self.transport_spec = adapter_path or _default_transport()
        self.alias = DEFAULT_ALIAS
        self.class_of_device = DEFAULT_CLASS_OF_DEVICE
        self.address = "00:00:00:00:00:00"
        self.powered = False
        self.pairable = True
        self.pairable_timeout = 0
        self.discoverable = False
        self.discoverable_timeout = 180
        self.sdp_record_xml: str | None = None
        self.runtime: _BumbleRuntime | None = None

    def _ensure_runtime(self) -> _BumbleRuntime:
        if self.runtime is None:
            self.runtime = _BumbleRuntime(
                transport_spec=self.transport_spec,
                alias=self.alias,
                class_of_device=self.class_of_device,
                discoverable=self.discoverable,
                connectable=self.powered,
                sdp_record_xml=self.sdp_record_xml,
            )
        return self.runtime

    def _sync_runtime_identity(self) -> None:
        if self.runtime is None:
            return
        self.runtime.alias = self.alias
        self.runtime.class_of_device = self.class_of_device
        self.runtime.connectable = self.powered
        self.runtime.discoverable = self.discoverable
        self.runtime.sdp_record_xml = self.sdp_record_xml
        self.address = self.runtime.address

    def set_powered(self, value: bool) -> None:
        self.powered = value
        if not value and self.runtime is not None:
            self.runtime.stop()
            self.address = self.runtime.address
            self.runtime = None

    def set_pairable(self, value: bool) -> None:
        self.pairable = value

    def set_pairable_timeout(self, value: int) -> None:
        self.pairable_timeout = value

    def set_discoverable_timeout(self, value: int) -> None:
        self.discoverable_timeout = value

    def set_alias(self, value: str) -> None:
        self.alias = value
        if self.runtime is not None:
            self.runtime.call(self.runtime.set_alias(value))
            self.address = self.runtime.address

    def register_profile(self, _profile_path: str, _uuid: str, opts: dict[str, Any]):
        service_record = opts.get("ServiceRecord")
        if service_record:
            self.sdp_record_xml = service_record
            if self.runtime is not None:
                self.runtime.call(self.runtime.update_sdp(service_record))

    def set_discoverable(self, value: bool) -> None:
        self.discoverable = value
        if self.runtime is not None:
            self.runtime.call(self.runtime.set_discoverable(value))

    def set_class(self, device_class: str | int) -> None:
        self.class_of_device = _parse_device_class(device_class)
        if self.runtime is not None:
            self.runtime.call(self.runtime.set_class(self.class_of_device))

    def find_connected_devices(self, alias_filter=False):
        if self.runtime is None:
            return []
        devices = list(self.runtime.connections.keys())
        if alias_filter:
            return devices
        return devices

    def remove_device(self, path: str) -> None:
        if self.runtime is not None:
            self.runtime.call(self.runtime.disconnect_peer(path))
        _delete_paired_address(path)

    def create_server_transport(self) -> _BumbleServerTransport:
        runtime = self._ensure_runtime()
        self._sync_runtime_identity()
        runtime.start()
        runtime.call(runtime.set_connectable(self.powered))
        self.address = runtime.address
        return _BumbleServerTransport(runtime)

    def create_reconnect_transport(self, reconnect_address):
        runtime = self._ensure_runtime()
        self._sync_runtime_identity()
        runtime.start()

        addresses = reconnect_address
        if isinstance(reconnect_address, str):
            addresses = [reconnect_address]

        last_error = None
        for address in addresses:
            try:
                sockets = runtime.call(runtime.reconnect(address))
                self.address = runtime.address
                return sockets
            except Exception as exc:
                last_error = exc

        raise OSError(
            "Unable to reconnect to sockets at the given address(es)",
            reconnect_address,
        ) from last_error

    def set_nonblocking(self, sock) -> None:
        sock.setblocking(False)

    def reset_address(self) -> None:
        if self.runtime is not None:
            self.runtime.stop()
            self.address = self.runtime.address
            self.runtime = None


def _delete_paired_address(address: str) -> None:
    keystore_path = _keystore_path()
    if not keystore_path.exists():
        return

    try:
        with open(keystore_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return

    changed = False
    for namespace in data.values():
        if not isinstance(namespace, dict):
            continue
        for key in list(namespace.keys()):
            if _address_to_string(key) == _address_to_string(address):
                del namespace[key]
                changed = True

    if not changed:
        return

    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    with open(keystore_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, indent=4)


def _read_paired_addresses() -> list[str]:
    keystore_path = _keystore_path()
    if not keystore_path.exists():
        return []

    try:
        with open(keystore_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []

    addresses = set()
    for namespace in data.values():
        if not isinstance(namespace, dict):
            continue
        addresses.update(_address_to_string(address) for address in namespace.keys())
    return sorted(addresses)


def _list_usb_adapters() -> list[str]:
    modules = _load_usb_modules()
    modules["load_libusb"]()
    usb1 = modules["usb1"]
    adapters = []

    context = usb1.USBContext()
    context.open()
    try:
        index = 0
        for device in context.getDeviceIterator(skip_on_error=True):
            try:
                for configuration in device:
                    found = False
                    for interface in configuration:
                        for setting in interface:
                            if (
                                setting.getClass(),
                                setting.getSubClass(),
                                setting.getProtocol(),
                            ) == (0xE0, 0x01, 0x01):
                                adapters.append(f"usb:{index}")
                                index += 1
                                found = True
                                break
                        if found:
                            break
                    if found:
                        break
            finally:
                device.close()
    finally:
        context.close()

    return adapters


class BumbleBackend(BaseBackend):
    name = "bumble"
    execution_mode = "thread"

    def validate_runtime(self) -> None:
        _load_bumble_modules()
        transport_spec = _default_transport()
        if transport_spec.startswith("usb:"):
            adapters = self.get_available_adapters()
            if not adapters:
                raise BackendUnavailableError(
                    "No Bumble-compatible USB Bluetooth adapters were found."
                )

    def setup(self) -> None:
        _state_dir().mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        return

    def get_available_adapters(self) -> list[str]:
        transport_spec = _default_transport()
        if transport_spec != DEFAULT_TRANSPORT:
            return [transport_spec]
        return _list_usb_adapters()

    def get_switch_addresses(self) -> list[str]:
        return _read_paired_addresses()

    def create_controller_adapter(
        self, adapter_path: str | None = None
    ) -> BumbleControllerAdapter:
        return BumbleControllerAdapter(adapter_path=adapter_path)

    def get_status(self) -> dict[str, Any]:
        try:
            _load_bumble_modules()
        except BackendUnavailableError as exc:
            return {
                "name": self.name,
                "supported": True,
                "available": False,
                "controller_transport_ready": False,
                "message": str(exc),
            }

        firmware_dir = _firmware_dir()
        transport_spec = _default_transport()
        adapters = []
        adapter_error = None
        try:
            adapters = self.get_available_adapters()
        except Exception as exc:  # pragma: no cover - host USB state
            adapter_error = str(exc)

        if adapter_error is not None:
            return {
                "name": self.name,
                "supported": True,
                "available": False,
                "controller_transport_ready": False,
                "transport": transport_spec,
                "firmware_dir": str(firmware_dir),
                "message": adapter_error,
            }

        available = bool(adapters)
        return {
            "name": self.name,
            "supported": True,
            "available": available,
            "controller_transport_ready": available,
            "transport": transport_spec,
            "available_adapters": adapters,
            "firmware_dir": str(firmware_dir),
            "firmware_files": sorted(
                file.name for file in firmware_dir.glob("*") if file.is_file()
            )
            if firmware_dir.exists()
            else [],
            "message": (
                "Bumble backend ready."
                if available
                else "No Bumble-compatible USB Bluetooth adapters were found."
            ),
        }
