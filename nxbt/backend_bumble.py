from __future__ import annotations

import asyncio
import hashlib
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


class _ReconnectAuthenticationError(RuntimeError):
    pass


class _ReconnectEncryptionError(RuntimeError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_dir() -> Path:
    return _repo_root() / ".bumble-state"


def _firmware_dir() -> Path:
    return Path(os.environ.get(FIRMWARE_ENV_VAR) or (_repo_root() / ".bumble-firmware"))


def _configured_keystore_path() -> Path | None:
    configured = os.environ.get(KEYSTORE_ENV_VAR)
    if configured:
        return Path(configured)
    return None


def _legacy_keystore_path() -> Path:
    return _state_dir() / "keys.json"


def _adapter_storage_key(adapter_path: str) -> str:
    normalized = adapter_path.strip()
    readable = "".join(
        character.lower() if character.isalnum() else "_"
        for character in normalized
    ).strip("_")
    if not readable:
        readable = "adapter"
    readable = readable[:48].rstrip("_")
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{readable}_{digest}"


def _keystore_path(adapter_path: str | None = None) -> Path:
    configured = _configured_keystore_path()
    if configured is not None:
        return configured
    if adapter_path is None:
        return _legacy_keystore_path()
    return _state_dir() / "keystores" / f"{_adapter_storage_key(adapter_path)}.json"


def _metadata_path(adapter_path: str) -> Path:
    return _state_dir() / "metadata" / f"{_adapter_storage_key(adapter_path)}.json"


def _default_transport() -> str:
    return os.environ.get(TRANSPORT_ENV_VAR, DEFAULT_TRANSPORT)


def _firmware_setup_instructions() -> list[str]:
    return [
        (
            "If this adapter is Realtek-based, install the Bumble firmware files "
            f"(for example {REALTEK_FIRMWARE_REFERENCE}) in '.bumble-firmware' "
            f"or point {FIRMWARE_ENV_VAR} to that directory."
        ),
        f"Reference: {REALTEK_FIRMWARE_HELP_URL}",
    ]


def _parse_device_class(device_class: str | int) -> int:
    if isinstance(device_class, int):
        return device_class
    return int(str(device_class), 16)


def _address_to_string(address: Any) -> str:
    if hasattr(address, "to_string"):
        return address.to_string(False)
    return str(address).split("/", 1)[0]


def _iter_exception_chain(exc: BaseException):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        yield current
        seen.add(id(current))
        current = current.__cause__ or current.__context__


def _is_page_timeout_error(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        error_name = getattr(candidate, "error_name", "")
        if error_name == "PAGE_TIMEOUT_ERROR":
            return True
        if "PAGE_TIMEOUT_ERROR" in str(candidate):
            return True
    return False


def _is_unacceptable_bd_addr_error(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        error_name = getattr(candidate, "error_name", "")
        if error_name == "CONNECTION_REJECTED_DUE_TO_UNACCEPTABLE_BD_ADDR_ERROR":
            return True
        if "CONNECTION_REJECTED_DUE_TO_UNACCEPTABLE_BD_ADDR_ERROR" in str(candidate):
            return True
    return False


def _is_reconnect_authentication_error(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        if isinstance(candidate, _ReconnectAuthenticationError):
            return True
    return False


def _build_reconnect_error(reconnect_address, last_error: BaseException) -> OSError:
    if _is_page_timeout_error(last_error):
        message = (
            "Unable to reconnect to the saved Switch because it did not answer "
            "the Bluetooth page request. Wake the Switch and keep it on the "
            "Home screen before retrying."
        )
        return OSError(message, reconnect_address)

    if _is_reconnect_authentication_error(last_error):
        message = (
            "Unable to reconnect because Bluetooth authentication did not complete "
            "for this adapter. This usually means this adapter's saved pairing for "
            "that Switch is stale or no longer matches the adapter's BD_ADDR. "
            "Remove the saved pairing for this adapter and pair it again from "
            "'Change Grip/Order', then retry reconnect."
        )
        return OSError(message, reconnect_address)

    if _is_unacceptable_bd_addr_error(last_error):
        message = (
            "Unable to reconnect because the Switch rejected this adapter's "
            "Bluetooth address. This usually means this specific adapter has not "
            "been paired with that Switch yet, or its saved pairing is stale. "
            "Pair this adapter once from 'Change Grip/Order' and then retry "
            "reconnect."
        )
        return OSError(message, reconnect_address)

    return OSError(
        "Unable to reconnect to sockets at the given address(es)",
        reconnect_address,
    )


def _looks_like_usb_error(exc: BaseException, marker: str) -> bool:
    marker = marker.upper()
    for candidate in _iter_exception_chain(exc):
        if marker in type(candidate).__name__.upper():
            return True
        if marker in str(candidate).upper():
            return True
    return False


def _build_transport_open_error(adapter_path: str, exc: BaseException) -> OSError:
    if _looks_like_usb_error(exc, "LIBUSB_ERROR_NOT_SUPPORTED") or _looks_like_usb_error(
        exc, "USBERRORNOTSUPPORTED"
    ):
        message = (
            f"Unable to open USB adapter '{adapter_path}'. libusb reported "
            "LIBUSB_ERROR_NOT_SUPPORTED. On Windows this usually means the selected "
            "dongle is not bound to a libusb-compatible driver instance. Reinstall "
            "WinUSB for that specific dongle with Zadig and retry."
        )
        return OSError(message)

    if _looks_like_usb_error(exc, "LIBUSB_ERROR_ACCESS") or _looks_like_usb_error(
        exc, "USBERRORACCESS"
    ):
        message = (
            f"Unable to open USB adapter '{adapter_path}'. libusb reported "
            "LIBUSB_ERROR_ACCESS. Another process or the Windows Bluetooth stack "
            "still owns this dongle, or this device instance is not using WinUSB."
        )
        return OSError(message)

    return OSError(f"Unable to open USB adapter '{adapter_path}': {exc}")


def _normalize_color_triplet(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None

    normalized = []
    for component in value:
        try:
            numeric = int(component)
        except (TypeError, ValueError):
            return None
        normalized.append(max(0, min(255, numeric)))
    return normalized


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
        adapter_id: str,
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
        self.keystore_path = _keystore_path(adapter_id)
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

        try:
            self.transport = await modules["open_transport"](self.transport_spec)
        except Exception as exc:
            raise _build_transport_open_error(self.transport_spec, exc) from exc
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
            try:
                await asyncio.wait_for(
                    connection.authenticate(),
                    timeout=CLASSIC_AUTH_TIMEOUT,
                )
            except Exception as exc:
                try:
                    await connection.disconnect()
                except Exception:
                    pass
                raise _ReconnectAuthenticationError(
                    "Bluetooth authentication did not complete during reconnect."
                ) from exc
        if not connection.encryption:
            try:
                await asyncio.wait_for(
                    connection.encrypt(),
                    timeout=CLASSIC_ENCRYPT_TIMEOUT,
                )
            except Exception as exc:
                try:
                    await connection.disconnect()
                except Exception:
                    pass
                raise _ReconnectEncryptionError(
                    "Bluetooth link encryption did not complete during reconnect."
                ) from exc
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
    def __init__(
        self,
        adapter_path: str | None = None,
        *,
        transport_spec: str | None = None,
        keystore_aliases: list[str] | None = None,
    ):
        self.adapter_path = adapter_path or _default_transport()
        self.transport_spec = transport_spec or self.adapter_path
        self.keystore_aliases = list(keystore_aliases or [])
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
                adapter_id=self.adapter_path,
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
        _delete_paired_address(path, self.adapter_path)
        for alias in self.keystore_aliases:
            _delete_paired_address(path, alias)

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

        raise _build_reconnect_error(reconnect_address, last_error) from last_error

    def set_nonblocking(self, sock) -> None:
        sock.setblocking(False)

    def reset_address(self) -> None:
        if self.runtime is not None:
            self.runtime.stop()
            self.address = self.runtime.address
            self.runtime = None


def _load_keystore_data(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _save_keystore_data(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, indent=4)


def _load_metadata_data(path: Path) -> dict[str, Any]:
    data = _load_keystore_data(path)
    if isinstance(data, dict):
        return data
    return {}


def _save_metadata_data(path: Path, data: dict[str, Any]) -> None:
    _save_keystore_data(path, data)


def _merge_mapping_file(target_path: Path, source_path: Path) -> None:
    if target_path == source_path:
        return

    source_data = _load_keystore_data(source_path)
    if not isinstance(source_data, dict) or not source_data:
        return

    target_data = _load_keystore_data(target_path)
    if not isinstance(target_data, dict):
        target_data = {}

    changed = False
    for key, value in source_data.items():
        if key not in target_data:
            target_data[key] = value
            changed = True
            continue

        if isinstance(target_data[key], dict) and isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if nested_key not in target_data[key]:
                    target_data[key][nested_key] = nested_value
                    changed = True

    if changed:
        _save_keystore_data(target_path, target_data)


def _iter_keystore_paths(adapter_path: str | None = None) -> list[Path]:
    configured = _configured_keystore_path()
    if configured is not None:
        return [configured]

    if adapter_path is not None:
        return [_keystore_path(adapter_path)]

    paths = []
    keystore_dir = _state_dir() / "keystores"
    if keystore_dir.exists():
        paths.extend(sorted(keystore_dir.glob("*.json")))

    legacy_path = _legacy_keystore_path()
    if legacy_path.exists():
        paths.append(legacy_path)

    return paths


def _delete_paired_address(address: str, adapter_path: str | None = None) -> None:
    changed = False
    for keystore_path in _iter_keystore_paths(adapter_path):
        data = _load_keystore_data(keystore_path)
        if not isinstance(data, dict):
            continue

        keystore_changed = False
        for namespace in data.values():
            if not isinstance(namespace, dict):
                continue
            for key in list(namespace.keys()):
                if _address_to_string(key) == _address_to_string(address):
                    del namespace[key]
                    keystore_changed = True

        if not keystore_changed:
            continue

        _save_keystore_data(keystore_path, data)
        changed = True

    if not changed:
        return


def _read_paired_addresses(adapter_path: str | None = None) -> list[str]:
    addresses = set()
    for keystore_path in _iter_keystore_paths(adapter_path):
        data = _load_keystore_data(keystore_path)
        if not isinstance(data, dict):
            continue
        for namespace in data.values():
            if not isinstance(namespace, dict):
                continue
            addresses.update(
                _address_to_string(address) for address in namespace.keys()
            )
    return sorted(addresses)


def _read_switch_metadata(adapter_path: str) -> dict[str, dict[str, list[int]]]:
    path = _metadata_path(adapter_path)
    data = _load_metadata_data(path)
    result = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        body_color = _normalize_color_triplet(value.get("colour_body"))
        button_color = _normalize_color_triplet(value.get("colour_buttons"))
        if body_color is None and button_color is None:
            continue
        entry = {}
        if body_color is not None:
            entry["colour_body"] = body_color
        if button_color is not None:
            entry["colour_buttons"] = button_color
        result[_address_to_string(key)] = entry
    return result


def _write_switch_metadata(
    adapter_path: str, address: str, metadata: dict[str, Any]
) -> None:
    body_color = _normalize_color_triplet(metadata.get("colour_body"))
    button_color = _normalize_color_triplet(metadata.get("colour_buttons"))
    if body_color is None and button_color is None:
        return

    path = _metadata_path(adapter_path)
    data = _load_metadata_data(path)
    normalized_address = _address_to_string(address)
    entry = dict(data.get(normalized_address, {}))
    if body_color is not None:
        entry["colour_body"] = body_color
    if button_color is not None:
        entry["colour_buttons"] = button_color
    data[normalized_address] = entry
    _save_metadata_data(path, data)


def _delete_switch_metadata(address: str, adapter_path: str | None = None) -> None:
    if not adapter_path:
        return

    path = _metadata_path(adapter_path)
    data = _load_metadata_data(path)
    if not data:
        return

    normalized_address = _address_to_string(address)
    if normalized_address not in data:
        return

    del data[normalized_address]
    _save_metadata_data(path, data)


def _merge_adapter_storage(adapter_path: str, aliases: list[str]) -> None:
    target_keystore = _keystore_path(adapter_path)
    target_metadata = _metadata_path(adapter_path)
    for alias in aliases:
        _merge_mapping_file(target_keystore, _keystore_path(alias))
        _merge_mapping_file(target_metadata, _metadata_path(alias))


def _device_matches_bluetooth_hci(device) -> bool:
    if (
        device.getDeviceClass(),
        device.getDeviceSubClass(),
        device.getDeviceProtocol(),
    ) == (0xE0, 0x01, 0x01):
        return True

    if device.getDeviceClass() != 0x00:
        return False

    for configuration in device:
        for interface in configuration:
            for setting in interface:
                if (
                    setting.getClass(),
                    setting.getSubClass(),
                    setting.getProtocol(),
                ) == (0xE0, 0x01, 0x01):
                    return True
    return False


def _usb_device_serial_spec(device) -> str | None:
    vendor_product = f"{device.getVendorID():04X}:{device.getProductID():04X}"
    try:
        serial_number = device.getSerialNumber()
    except Exception:
        serial_number = None
    if serial_number:
        return f"usb:{vendor_product}/{serial_number}"
    return None


def _usb_device_port_spec(device) -> str | None:
    try:
        bus_number = device.getBusNumber()
        port_numbers = list(device.getPortNumberList())
    except Exception:
        bus_number = None
        port_numbers = []
    if bus_number is not None and port_numbers:
        port_path = ".".join(str(number) for number in port_numbers)
        return f"usb:{bus_number}-{port_path}"
    return None


def _usb_transport_spec(device, duplicate_counts: dict[str, int]) -> str:
    port_spec = _usb_device_port_spec(device)
    if port_spec is not None:
        return port_spec

    serial_spec = _usb_device_serial_spec(device)
    if serial_spec is not None:
        return serial_spec

    vendor_product = f"{device.getVendorID():04X}:{device.getProductID():04X}"

    duplicate_index = duplicate_counts.get(vendor_product, 0)
    duplicate_counts[vendor_product] = duplicate_index + 1
    if duplicate_index == 0:
        return f"usb:{vendor_product}"
    return f"usb:{vendor_product}#{duplicate_index}"


def _usb_adapter_descriptor(device, duplicate_counts: dict[str, int]) -> dict[str, Any]:
    adapter_id = _usb_transport_spec(device, duplicate_counts)
    aliases = []
    serial_spec = _usb_device_serial_spec(device)
    if serial_spec is not None and serial_spec != adapter_id:
        aliases.append(serial_spec)
    probe_error = None
    try:
        handle = device.open()
        handle.close()
    except Exception as exc:
        probe_error = _build_transport_open_error(adapter_id, exc)
    return {
        "id": adapter_id,
        "transport_spec": adapter_id,
        "aliases": aliases,
        "probe_error": str(probe_error) if probe_error is not None else "",
        "is_available": probe_error is None,
    }


def _list_usb_adapter_descriptors() -> list[dict[str, Any]]:
    modules = _load_usb_modules()
    modules["load_libusb"]()
    usb1 = modules["usb1"]
    descriptors = []
    duplicate_counts: dict[str, int] = {}

    context = usb1.USBContext()
    context.open()
    try:
        for device in context.getDeviceIterator(skip_on_error=True):
            try:
                if _device_matches_bluetooth_hci(device):
                    descriptors.append(_usb_adapter_descriptor(device, duplicate_counts))
            finally:
                device.close()
    finally:
        context.close()

    return descriptors


def _list_usb_adapters() -> list[str]:
    return [descriptor["id"] for descriptor in _list_usb_adapter_descriptors()]


def _resolve_usb_adapter_descriptor(adapter_path: str) -> dict[str, Any] | None:
    for descriptor in _list_usb_adapter_descriptors():
        if adapter_path == descriptor["id"]:
            return descriptor
        if adapter_path in descriptor.get("aliases", []):
            return descriptor
    return None


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
        return [
            descriptor["id"]
            for descriptor in _list_usb_adapter_descriptors()
            if descriptor.get("is_available", True)
        ]

    def get_switch_addresses(self, adapter_path: str | None = None) -> list[str]:
        if adapter_path is not None:
            descriptor = _resolve_usb_adapter_descriptor(adapter_path)
            if descriptor is not None:
                addresses = set(_read_paired_addresses(descriptor["id"]))
                for alias in descriptor.get("aliases", []):
                    addresses.update(_read_paired_addresses(alias))
                return sorted(addresses)
        return _read_paired_addresses(adapter_path)

    def get_switch_metadata(
        self, adapter_path: str | None, address: str
    ) -> dict[str, Any] | None:
        if not adapter_path:
            return None

        descriptor = _resolve_usb_adapter_descriptor(adapter_path)
        candidates = [adapter_path]
        if descriptor is not None:
            candidates = [descriptor["id"], *descriptor.get("aliases", [])]

        normalized_address = _address_to_string(address)
        for candidate in candidates:
            metadata = _read_switch_metadata(candidate).get(normalized_address)
            if metadata:
                return metadata
        return None

    def save_switch_metadata(
        self, adapter_path: str | None, address: str, metadata: dict[str, Any]
    ) -> None:
        if not adapter_path or not address:
            return

        descriptor = _resolve_usb_adapter_descriptor(adapter_path)
        target_adapter = descriptor["id"] if descriptor is not None else adapter_path
        _write_switch_metadata(target_adapter, address, metadata)

    def forget_switch_pairing(self, adapter_path: str | None, address: str) -> None:
        if not adapter_path or not address:
            return

        descriptor = _resolve_usb_adapter_descriptor(adapter_path)
        candidates = [adapter_path]
        if descriptor is not None:
            candidates = [descriptor["id"], *descriptor.get("aliases", [])]

        for candidate in candidates:
            _delete_paired_address(address, candidate)
            _delete_switch_metadata(address, candidate)

    def create_controller_adapter(
        self, adapter_path: str | None = None
    ) -> BumbleControllerAdapter:
        transport_spec = adapter_path or _default_transport()
        resolved_adapter_path = adapter_path or transport_spec
        aliases: list[str] = []
        if adapter_path is not None:
            descriptor = _resolve_usb_adapter_descriptor(adapter_path)
            if descriptor is not None:
                resolved_adapter_path = descriptor["id"]
                transport_spec = descriptor["transport_spec"]
                aliases = list(descriptor.get("aliases", []))
                _merge_adapter_storage(resolved_adapter_path, aliases)
        return BumbleControllerAdapter(
            adapter_path=resolved_adapter_path,
            transport_spec=transport_spec,
            keystore_aliases=aliases,
        )

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
                "firmware_files": sorted(
                    file.name for file in firmware_dir.glob("*") if file.is_file()
                )
                if firmware_dir.exists()
                else [],
                "firmware_reference": REALTEK_FIRMWARE_REFERENCE,
                "firmware_help_url": REALTEK_FIRMWARE_HELP_URL,
                "firmware_setup_instructions": _firmware_setup_instructions(),
                "message": adapter_error,
            }

        available = bool(adapters)
        adapter_details = _list_usb_adapter_descriptors()
        unavailable_adapter_details = [
            descriptor
            for descriptor in adapter_details
            if not descriptor.get("is_available", True)
        ]
        firmware_files = (
            sorted(file.name for file in firmware_dir.glob("*") if file.is_file())
            if firmware_dir.exists()
            else []
        )
        firmware_instructions = _firmware_setup_instructions()
        return {
            "name": self.name,
            "supported": True,
            "available": available,
            "controller_transport_ready": available,
            "transport": transport_spec,
            "available_adapters": adapters,
            "available_adapter_details": adapter_details,
            "unavailable_adapter_details": unavailable_adapter_details,
            "firmware_dir": str(firmware_dir),
            "firmware_files": firmware_files,
            "firmware_reference": REALTEK_FIRMWARE_REFERENCE,
            "firmware_help_url": REALTEK_FIRMWARE_HELP_URL,
            "firmware_setup_instructions": firmware_instructions,
            "message": (
                "Bumble backend ready."
                if available
                else "No Bumble-compatible USB Bluetooth adapters were found."
            ),
        }
