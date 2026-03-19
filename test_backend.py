import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nxbt.backend import get_backend, resolve_backend_name
from nxbt.backend_bumble import (
    _ReconnectAuthenticationError,
    BumbleControllerAdapter,
    _adapter_storage_key,
    _build_transport_open_error,
    _merge_adapter_storage,
    _read_switch_metadata,
    _read_paired_addresses,
    _usb_adapter_descriptor,
    _usb_transport_spec,
    _write_switch_metadata,
)


class BackendSelectionTests(unittest.TestCase):
    def test_auto_backend_matches_platform(self):
        if sys.platform.startswith("linux"):
            self.assertEqual(resolve_backend_name("auto"), "linux")
        elif sys.platform == "win32":
            self.assertEqual(resolve_backend_name("auto"), "bumble")
        else:
            self.assertEqual(resolve_backend_name("auto"), "bumble")

    def test_default_backend_exposes_status(self):
        backend = get_backend()
        status = backend.get_status()

        self.assertEqual(status["name"], resolve_backend_name("auto"))
        self.assertIn("message", status)


class _FakeBumbleError(Exception):
    def __init__(self, error_name=""):
        super().__init__(error_name)
        self.error_name = error_name


class _FakeReconnectRuntime:
    def __init__(self, error):
        self.error = error
        self.alias = ""
        self.class_of_device = 0
        self.connectable = False
        self.discoverable = False
        self.sdp_record_xml = None
        self.address = "00:00:00:00:00:00"

    def start(self):
        return None

    def reconnect(self, address):
        return address

    def call(self, _coroutine):
        raise self.error


class BumbleReconnectErrorTests(unittest.TestCase):
    def test_reconnect_page_timeout_has_helpful_message(self):
        adapter = BumbleControllerAdapter(adapter_path="usb:0")
        adapter.runtime = _FakeReconnectRuntime(
            _FakeBumbleError(error_name="PAGE_TIMEOUT_ERROR")
        )

        with self.assertRaisesRegex(
            OSError, "Wake the Switch and keep it on the Home screen"
        ):
            adapter.create_reconnect_transport("B8:8A:EC:89:03:0E")

    def test_reconnect_other_errors_keep_generic_message(self):
        adapter = BumbleControllerAdapter(adapter_path="usb:0")
        adapter.runtime = _FakeReconnectRuntime(
            _FakeBumbleError(error_name="CONNECTION_ALREADY_EXISTS_ERROR")
        )

        with self.assertRaisesRegex(
            OSError, "Unable to reconnect to sockets at the given address"
        ):
            adapter.create_reconnect_transport("B8:8A:EC:89:03:0E")

    def test_reconnect_unacceptable_bd_addr_has_helpful_message(self):
        adapter = BumbleControllerAdapter(adapter_path="usb:0")
        adapter.runtime = _FakeReconnectRuntime(
            _FakeBumbleError(
                error_name="CONNECTION_REJECTED_DUE_TO_UNACCEPTABLE_BD_ADDR_ERROR"
            )
        )

        with self.assertRaisesRegex(
            OSError, "Pair this adapter once from 'Change Grip/Order'"
        ):
            adapter.create_reconnect_transport("B8:8A:EC:89:03:0E")

    def test_reconnect_authentication_timeout_has_helpful_message(self):
        adapter = BumbleControllerAdapter(adapter_path="usb:0")
        adapter.runtime = _FakeReconnectRuntime(
            _ReconnectAuthenticationError("Bluetooth authentication did not complete")
        )

        with self.assertRaisesRegex(
            OSError, "saved pairing for that Switch is stale"
        ):
            adapter.create_reconnect_transport("B8:8A:EC:89:03:0E")


class _FakeUsbDevice:
    def __init__(
        self,
        *,
        vendor_id,
        product_id,
        serial_number=None,
        bus_number=None,
        port_numbers=None,
    ):
        self._vendor_id = vendor_id
        self._product_id = product_id
        self._serial_number = serial_number
        self._bus_number = bus_number
        self._port_numbers = port_numbers or []
        self._open_error = None

    def getVendorID(self):
        return self._vendor_id

    def getProductID(self):
        return self._product_id

    def getSerialNumber(self):
        if self._serial_number is None:
            raise ValueError("serial not available")
        return self._serial_number

    def getBusNumber(self):
        if self._bus_number is None:
            raise ValueError("bus not available")
        return self._bus_number

    def getPortNumberList(self):
        return list(self._port_numbers)

    def open(self):
        if self._open_error is not None:
            raise self._open_error
        return self

    def close(self):
        return None


class BumbleAdapterPersistenceTests(unittest.TestCase):
    def test_adapter_storage_key_is_stable_and_unique(self):
        adapter_a = "usb:13D3:3571/ABC123"
        adapter_b = "usb:13D3:3571/XYZ999"

        self.assertEqual(_adapter_storage_key(adapter_a), _adapter_storage_key(adapter_a))
        self.assertNotEqual(_adapter_storage_key(adapter_a), _adapter_storage_key(adapter_b))

    def test_read_paired_addresses_is_scoped_per_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            keystore_dir = state_dir / "keystores"
            keystore_dir.mkdir(parents=True, exist_ok=True)
            adapter_a = "usb:13D3:3571/ABC123"
            adapter_b = "usb:13D3:3571/XYZ999"

            adapter_a_keystore = keystore_dir / f"{_adapter_storage_key(adapter_a)}.json"
            adapter_a_keystore.write_text(
                '{"classic": {"AA:AA:AA:AA:AA:AA": {"key": "a"}}}',
                encoding="utf-8",
            )
            adapter_b_keystore = keystore_dir / f"{_adapter_storage_key(adapter_b)}.json"
            adapter_b_keystore.write_text(
                '{"classic": {"BB:BB:BB:BB:BB:BB": {"key": "b"}}}',
                encoding="utf-8",
            )

            with mock.patch("nxbt.backend_bumble._state_dir", return_value=state_dir):
                self.assertEqual(
                    _read_paired_addresses(adapter_a),
                    ["AA:AA:AA:AA:AA:AA"],
                )
                self.assertEqual(
                    _read_paired_addresses(adapter_b),
                    ["BB:BB:BB:BB:BB:BB"],
                )
                self.assertEqual(
                    _read_paired_addresses(),
                    ["AA:AA:AA:AA:AA:AA", "BB:BB:BB:BB:BB:BB"],
                )

    def test_read_paired_addresses_supports_legacy_alias_keystore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            keystore_dir = state_dir / "keystores"
            keystore_dir.mkdir(parents=True, exist_ok=True)
            legacy_alias = "usb:13D3:3571/ABC123"

            alias_keystore = keystore_dir / f"{_adapter_storage_key(legacy_alias)}.json"
            alias_keystore.write_text(
                '{"classic": {"CC:CC:CC:CC:CC:CC": {"key": "c"}}}',
                encoding="utf-8",
            )

            with mock.patch("nxbt.backend_bumble._state_dir", return_value=state_dir):
                self.assertEqual(
                    _read_paired_addresses(legacy_alias),
                    ["CC:CC:CC:CC:CC:CC"],
                )

    def test_switch_metadata_is_scoped_per_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            adapter_a = "usb:2-6.3"
            adapter_b = "usb:2-6.4"

            with mock.patch("nxbt.backend_bumble._state_dir", return_value=state_dir):
                _write_switch_metadata(
                    adapter_a,
                    "AA:AA:AA:AA:AA:AA",
                    {
                        "colour_body": [1, 2, 3],
                        "colour_buttons": [4, 5, 6],
                    },
                )
                _write_switch_metadata(
                    adapter_b,
                    "BB:BB:BB:BB:BB:BB",
                    {
                        "colour_body": [7, 8, 9],
                        "colour_buttons": [10, 11, 12],
                    },
                )

                self.assertEqual(
                    _read_switch_metadata(adapter_a)["AA:AA:AA:AA:AA:AA"]["colour_body"],
                    [1, 2, 3],
                )
                self.assertEqual(
                    _read_switch_metadata(adapter_b)["BB:BB:BB:BB:BB:BB"]["colour_buttons"],
                    [10, 11, 12],
                )

    def test_forget_pairing_removes_metadata_and_keystore_for_selected_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            adapter = "usb:2-6.4"
            address = "AA:AA:AA:AA:AA:AA"

            with mock.patch("nxbt.backend_bumble._state_dir", return_value=state_dir):
                _write_switch_metadata(
                    adapter,
                    address,
                    {
                        "colour_body": [1, 2, 3],
                        "colour_buttons": [4, 5, 6],
                    },
                )
                keystore_dir = state_dir / "keystores"
                keystore_dir.mkdir(parents=True, exist_ok=True)
                (keystore_dir / f"{_adapter_storage_key(adapter)}.json").write_text(
                    '{"classic": {"AA:AA:AA:AA:AA:AA": {"key": "a"}}}',
                    encoding="utf-8",
                )

                backend = get_backend("bumble")
                backend.forget_switch_pairing(adapter, address)

                self.assertEqual(_read_switch_metadata(adapter), {})
                self.assertEqual(_read_paired_addresses(adapter), [])

    def test_merge_adapter_storage_moves_alias_keystore_data_to_canonical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            keystore_dir = state_dir / "keystores"
            keystore_dir.mkdir(parents=True, exist_ok=True)
            canonical = "usb:2-6.4"
            alias = "usb:2B89:8761/00E04C239987"

            alias_keystore = keystore_dir / f"{_adapter_storage_key(alias)}.json"
            alias_keystore.write_text(
                '{"00:A6:44:02:4D:19/P": {"B8:8A:EC:89:03:0E/P": {"link_key": {"value": "abc", "authenticated": false}, "link_key_type": 4}}}',
                encoding="utf-8",
            )

            with mock.patch("nxbt.backend_bumble._state_dir", return_value=state_dir):
                _merge_adapter_storage(canonical, [alias])

                self.assertEqual(
                    _read_paired_addresses(canonical),
                    ["B8:8A:EC:89:03:0E"],
                )

    def test_usb_transport_spec_prefers_port_path_then_serial(self):
        duplicate_counts = {}

        self.assertEqual(
            _usb_transport_spec(
                _FakeUsbDevice(
                    vendor_id=0x13D3,
                    product_id=0x3571,
                    bus_number=3,
                    port_numbers=[4, 1],
                    serial_number="ABC123",
                ),
                duplicate_counts,
            ),
            "usb:3-4.1",
        )
        self.assertEqual(
            _usb_transport_spec(
                _FakeUsbDevice(
                    vendor_id=0x13D3,
                    product_id=0x3571,
                    bus_number=3,
                    port_numbers=[4, 1],
                ),
                duplicate_counts,
            ),
            "usb:3-4.1",
        )

    def test_usb_adapter_descriptor_keeps_serial_as_alias(self):
        descriptor = _usb_adapter_descriptor(
            _FakeUsbDevice(
                vendor_id=0x13D3,
                product_id=0x3571,
                serial_number="ABC123",
                bus_number=3,
                port_numbers=[4, 1],
            ),
            {},
        )

        self.assertEqual(descriptor["id"], "usb:3-4.1")
        self.assertEqual(descriptor["transport_spec"], "usb:3-4.1")
        self.assertEqual(descriptor["aliases"], ["usb:13D3:3571/ABC123"])

    def test_usb_adapter_descriptor_marks_unopenable_devices(self):
        device = _FakeUsbDevice(
            vendor_id=0x13D3,
            product_id=0x3571,
            bus_number=3,
            port_numbers=[4, 1],
        )
        device._open_error = RuntimeError("LIBUSB_ERROR_NOT_SUPPORTED [-12]")

        descriptor = _usb_adapter_descriptor(device, {})

        self.assertFalse(descriptor["is_available"])
        self.assertIn("LIBUSB_ERROR_NOT_SUPPORTED", descriptor["probe_error"])

    def test_transport_open_error_explains_access_error(self):
        error = _build_transport_open_error(
            "usb:3-4.1",
            RuntimeError("LIBUSB_ERROR_ACCESS [-3]"),
        )

        self.assertIn("LIBUSB_ERROR_ACCESS", str(error))
        self.assertIn("WinUSB", str(error))


if __name__ == "__main__":
    unittest.main()
