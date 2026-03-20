import os
import unittest
from pathlib import Path
from unittest import mock

from nxbt.qt.controller_manager import ControllerManager
from nxbt.qt.input_backends.base import BaseInputBackend
from nxbt.qt.input_backends.keyboard import KeyboardInputBackend
from nxbt.qt.input_backends.manager import InputBackendManager
from nxbt.qt.models import InputProvider

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication

    from nxbt.qt.widgets.create_controller_dialog import CreateControllerDialog
except Exception:  # pragma: no cover - optional desktop dependency
    QApplication = None
    CreateControllerDialog = None


class FakeNxbt:
    def __init__(self):
        self.created = []
        self.removed = []
        self.macros = []
        self.inputs = []
        self.forgot_pairings = []
        self._controller_counter = 0
        self._state = {}
        self.saved_addresses = {
            "adapter-0": ["AA:BB:CC:DD:EE:FF"],
            "adapter-1": ["11:22:33:44:55:66"],
        }
        self.saved_metadata = {
            ("adapter-0", "AA:BB:CC:DD:EE:FF"): {
                "colour_body": [10, 20, 30],
                "colour_buttons": [40, 50, 60],
            },
            ("adapter-1", "11:22:33:44:55:66"): {
                "colour_body": [70, 80, 90],
                "colour_buttons": [100, 110, 120],
            },
        }

    def get_backend_status(self):
        return {"name": "fake"}

    def get_available_adapters(self):
        return ["adapter-0", "adapter-1"]

    def get_switch_addresses(self, adapter_path=None):
        if adapter_path is None:
            addresses = []
            for saved in self.saved_addresses.values():
                addresses.extend(saved)
            return addresses
        return list(self.saved_addresses.get(adapter_path, []))

    def get_switch_metadata(self, adapter_path, address):
        return self.saved_metadata.get((adapter_path, address))

    def forget_switch_pairing(self, adapter_path, address):
        self.forgot_pairings.append((adapter_path, address))
        self.saved_addresses.setdefault(adapter_path, [])
        if address in self.saved_addresses[adapter_path]:
            self.saved_addresses[adapter_path].remove(address)
        self.saved_metadata.pop((adapter_path, address), None)

    def create_controller(
        self,
        controller_type,
        adapter_path=None,
        colour_body=None,
        colour_buttons=None,
        reconnect_address=None,
    ):
        controller_index = self._controller_counter
        self._controller_counter += 1
        self.created.append(
            {
                "controller_type": controller_type,
                "adapter_path": adapter_path,
                "colour_body": colour_body,
                "colour_buttons": colour_buttons,
                "reconnect_address": reconnect_address,
            }
        )
        self._state[controller_index] = {
            "state": "connecting",
            "errors": "",
            "finished_macros": [],
        }
        return controller_index

    def remove_controller(self, controller_index):
        self.removed.append(controller_index)
        self._state.pop(controller_index, None)

    def macro(self, controller_index, macro, block=False):
        macro_id = f"macro-{controller_index}-{len(self.macros)}"
        self.macros.append((controller_index, macro, block, macro_id))
        return macro_id

    def clear_macros(self, controller_index):
        self.macros.append((controller_index, "CLEAR", False, None))

    def set_controller_input(self, controller_index, packet):
        self.inputs.append((controller_index, packet))

    @property
    def state(self):
        return self._state

    def _on_exit(self):
        return


class FakeProviderBackend(BaseInputBackend):
    backend_id = "fake"

    def __init__(self):
        super().__init__()
        self.claimed = set()
        self.providers = [
            InputProvider("fake", "pad-1", "Pad 1"),
            InputProvider("fake", "pad-2", "Pad 2"),
        ]

    def list_providers(self):
        return list(self.providers)

    def claim(self, provider_id, controller_index):
        self.claimed.add((provider_id, controller_index))

    def release(self, provider_id, controller_index):
        self.claimed.discard((provider_id, controller_index))

    def poll(self):
        packets = {}
        for provider_id, _controller_index in self.claimed:
            packets[provider_id] = {"provider": provider_id}
        return packets


class FakeSdl3Gamepad:
    def __init__(self, *, instance_id, name, axes=None, buttons=None, connected=True):
        self.instance_id = instance_id
        self.name = name
        self.axes = dict(axes or {})
        self.buttons = dict(buttons or {})
        self.connected = connected


class FakeSdl3Module:
    SDL_INIT_GAMEPAD = 0x00002000
    SDL_INIT_EVENTS = 0x00004000

    SDL_GAMEPAD_AXIS_LEFTX = 0
    SDL_GAMEPAD_AXIS_LEFTY = 1
    SDL_GAMEPAD_AXIS_RIGHTX = 2
    SDL_GAMEPAD_AXIS_RIGHTY = 3
    SDL_GAMEPAD_AXIS_LEFT_TRIGGER = 4
    SDL_GAMEPAD_AXIS_RIGHT_TRIGGER = 5

    SDL_GAMEPAD_BUTTON_SOUTH = 0
    SDL_GAMEPAD_BUTTON_EAST = 1
    SDL_GAMEPAD_BUTTON_WEST = 2
    SDL_GAMEPAD_BUTTON_NORTH = 3
    SDL_GAMEPAD_BUTTON_BACK = 4
    SDL_GAMEPAD_BUTTON_GUIDE = 5
    SDL_GAMEPAD_BUTTON_START = 6
    SDL_GAMEPAD_BUTTON_LEFT_STICK = 7
    SDL_GAMEPAD_BUTTON_RIGHT_STICK = 8
    SDL_GAMEPAD_BUTTON_LEFT_SHOULDER = 9
    SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER = 10
    SDL_GAMEPAD_BUTTON_DPAD_UP = 11
    SDL_GAMEPAD_BUTTON_DPAD_DOWN = 12
    SDL_GAMEPAD_BUTTON_DPAD_LEFT = 13
    SDL_GAMEPAD_BUTTON_DPAD_RIGHT = 14
    SDL_GAMEPAD_BUTTON_MISC1 = 15
    SDL_GAMEPAD_BUTTON_TOUCHPAD = 21

    def __init__(self, gamepads):
        self.gamepads = {gamepad.instance_id: gamepad for gamepad in gamepads}
        self.closed = []
        self.init_calls = 0
        self.quit_calls = 0

    def SDL_InitSubSystem(self, _flags):
        self.init_calls += 1
        return True

    def SDL_QuitSubSystem(self, _flags):
        self.quit_calls += 1

    def SDL_GetGamepads(self, count_ptr):
        count_ptr._obj.value = len(self.gamepads)
        return list(self.gamepads.keys())

    def SDL_GetGamepadNameForID(self, instance_id):
        return self.gamepads[int(instance_id)].name.encode("utf-8")

    def SDL_OpenGamepad(self, instance_id):
        return self.gamepads.get(int(instance_id))

    def SDL_CloseGamepad(self, gamepad):
        self.closed.append(gamepad.instance_id)

    def SDL_GamepadConnected(self, gamepad):
        return gamepad.connected

    def SDL_PumpEvents(self):
        return None

    def SDL_GetGamepadAxis(self, gamepad, axis):
        return gamepad.axes.get(axis, 0)

    def SDL_GetGamepadButton(self, gamepad, button):
        return 1 if gamepad.buttons.get(button, False) else 0

    def SDL_GetError(self):
        return b"fake sdl3 error"

    def SDL_GET_BINARY(self, name):
        if name == "SDL3":
            return object()
        return None


class FakeSdl3MissingRuntime(FakeSdl3Module):
    def SDL_GET_BINARY(self, name):
        return None


class ControllerManagerTests(unittest.TestCase):
    def test_create_session_claims_adapter_and_colors(self):
        nx = FakeNxbt()
        manager = ControllerManager(nx=nx)

        session = manager.create_session(
            adapter_path="adapter-0",
            body_color=(10, 20, 30),
            button_color=(40, 50, 60),
            reconnect_target="AA:BB:CC:DD:EE:FF",
        )

        self.assertEqual(session.adapter_path, "adapter-0")
        self.assertEqual(manager.get_free_adapters(), ["adapter-1"])
        self.assertEqual(nx.created[0]["colour_body"], [10, 20, 30])
        self.assertEqual(nx.created[0]["colour_buttons"], [40, 50, 60])
        self.assertEqual(nx.created[0]["reconnect_address"], "AA:BB:CC:DD:EE:FF")

    def test_send_input_updates_session_preview(self):
        nx = FakeNxbt()
        manager = ControllerManager(nx=nx)
        session = manager.create_session(
            adapter_path="adapter-0",
            body_color=(10, 20, 30),
            button_color=(40, 50, 60),
            reconnect_target=None,
        )
        packet = session.last_input_packet
        packet["A"] = True

        manager.send_input(session.controller_index, packet)

        self.assertTrue(
            manager.get_session(session.controller_index).last_input_packet["A"]
        )
        self.assertEqual(nx.inputs[-1][0], session.controller_index)

    def test_saved_switch_addresses_are_filtered_by_adapter(self):
        manager = ControllerManager(nx=FakeNxbt())

        self.assertEqual(
            manager.get_saved_switch_addresses("adapter-0"),
            ["AA:BB:CC:DD:EE:FF"],
        )
        self.assertEqual(
            manager.get_saved_switch_addresses("adapter-1"),
            ["11:22:33:44:55:66"],
        )

    def test_saved_switch_addresses_are_grouped_by_adapter(self):
        manager = ControllerManager(nx=FakeNxbt())

        addresses = manager.get_saved_switch_addresses_by_adapter(
            ["adapter-0", "adapter-1"]
        )

        self.assertEqual(addresses["adapter-0"], ["AA:BB:CC:DD:EE:FF"])
        self.assertEqual(addresses["adapter-1"], ["11:22:33:44:55:66"])

    def test_saved_switch_metadata_is_grouped_by_adapter(self):
        manager = ControllerManager(nx=FakeNxbt())

        metadata = manager.get_saved_switch_metadata_by_adapter(
            ["adapter-0", "adapter-1"]
        )

        self.assertEqual(
            metadata["adapter-0"]["AA:BB:CC:DD:EE:FF"]["colour_body"],
            [10, 20, 30],
        )
        self.assertEqual(
            metadata["adapter-1"]["11:22:33:44:55:66"]["colour_buttons"],
            [100, 110, 120],
        )

    def test_forget_saved_switch_removes_pairing_for_selected_adapter(self):
        nx = FakeNxbt()
        manager = ControllerManager(nx=nx)

        manager.forget_saved_switch("adapter-0", "AA:BB:CC:DD:EE:FF")

        self.assertEqual(
            nx.forgot_pairings,
            [("adapter-0", "AA:BB:CC:DD:EE:FF")],
        )


@unittest.skipIf(
    QApplication is None or CreateControllerDialog is None,
    "PyQt6 is not available",
)
class CreateControllerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_lists_saved_addresses_without_metadata(self):
        dialog = CreateControllerDialog(
            adapters=["adapter-0"],
            saved_addresses_by_adapter={
                "adapter-0": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
            },
            saved_metadata_by_adapter={
                "adapter-0": {
                    "AA:BB:CC:DD:EE:FF": {
                        "colour_body": [10, 20, 30],
                        "colour_buttons": [40, 50, 60],
                    }
                }
            },
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.reconnect_combo.count(), 3)
        self.assertEqual(
            dialog.reconnect_combo.itemData(1),
            "AA:BB:CC:DD:EE:FF",
        )
        self.assertEqual(
            dialog.reconnect_combo.itemData(2),
            "11:22:33:44:55:66",
        )

        dialog.reconnect_combo.setCurrentIndex(2)

        self.assertEqual(
            dialog.body_color(),
            CreateControllerDialog.DEFAULT_BODY_COLOR,
        )
        self.assertEqual(
            dialog.button_color(),
            CreateControllerDialog.DEFAULT_BUTTON_COLOR,
        )


class InputBackendManagerTests(unittest.TestCase):
    def test_keyboard_backend_updates_sticks_and_presses(self):
        backend = KeyboardInputBackend()
        backend.claim("keyboard", 0)

        self.assertTrue(backend.handle_key_press("W"))
        self.assertTrue(backend.handle_key_press("D"))
        self.assertTrue(backend.handle_key_press("T"))
        packet = backend.poll()["keyboard"]

        self.assertEqual(packet["L_STICK"]["X_VALUE"], 100)
        self.assertEqual(packet["L_STICK"]["Y_VALUE"], 100)
        self.assertTrue(packet["L_STICK"]["PRESSED"])

        backend.handle_key_release("W")
        backend.handle_key_release("D")
        backend.handle_key_release("T")
        packet = backend.poll()["keyboard"]
        self.assertEqual(packet["L_STICK"]["X_VALUE"], 0)
        self.assertEqual(packet["L_STICK"]["Y_VALUE"], 0)
        self.assertFalse(packet["L_STICK"]["PRESSED"])

    def test_manager_enforces_unique_provider_assignment(self):
        manager = InputBackendManager(backends=[KeyboardInputBackend(), FakeProviderBackend()])
        manager.assign_provider(0, "pad-1")

        with self.assertRaises(ValueError):
            manager.assign_provider(1, "pad-1")

        providers = manager.list_assignable_providers(1)
        provider_ids = [provider.provider_id for provider in providers]
        self.assertNotIn("pad-1", provider_ids)
        self.assertIn("pad-2", provider_ids)

    def test_sdl3_backend_enumerates_gamepads_with_details(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        backend = Sdl3GamepadBackend()
        backend._sdl3 = FakeSdl3Module(
            [
                FakeSdl3Gamepad(instance_id=11, name="DualSense"),
                FakeSdl3Gamepad(instance_id=22, name="Xbox Wireless Controller"),
            ]
        )

        providers = backend.list_providers()

        self.assertEqual(len(providers), 2)
        self.assertEqual(providers[0].provider_id, "gamepad:11")
        self.assertEqual(providers[0].profile_label, "SDL3 Gamepad")
        self.assertIn("Instance ID: 11", providers[0].details)

    def test_sdl3_backend_maps_standard_gamepad_layout(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        fake_sdl3 = FakeSdl3Module(
            [
                FakeSdl3Gamepad(
                    instance_id=7,
                    name="DualSense",
                    axes={
                        FakeSdl3Module.SDL_GAMEPAD_AXIS_LEFTX: 8192,
                        FakeSdl3Module.SDL_GAMEPAD_AXIS_LEFTY: -16384,
                        FakeSdl3Module.SDL_GAMEPAD_AXIS_RIGHTX: -24576,
                        FakeSdl3Module.SDL_GAMEPAD_AXIS_RIGHTY: 12288,
                        FakeSdl3Module.SDL_GAMEPAD_AXIS_LEFT_TRIGGER: 20000,
                        FakeSdl3Module.SDL_GAMEPAD_AXIS_RIGHT_TRIGGER: 22000,
                    },
                    buttons={
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_SOUTH: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_EAST: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_LEFT_SHOULDER: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_BACK: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_START: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_GUIDE: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_LEFT_STICK: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_RIGHT_STICK: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_DPAD_RIGHT: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_DPAD_DOWN: True,
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_MISC1: True,
                    },
                )
            ]
        )
        backend = Sdl3GamepadBackend()
        backend._sdl3 = fake_sdl3

        providers = backend.list_providers()
        backend.claim(providers[0].provider_id, 0)
        packet = backend.poll()[providers[0].provider_id]

        self.assertEqual(packet["L_STICK"]["X_VALUE"], 25)
        self.assertEqual(packet["L_STICK"]["Y_VALUE"], 50)
        self.assertEqual(packet["R_STICK"]["X_VALUE"], -75)
        self.assertEqual(packet["R_STICK"]["Y_VALUE"], -38)
        self.assertTrue(packet["L_STICK"]["PRESSED"])
        self.assertTrue(packet["R_STICK"]["PRESSED"])
        self.assertTrue(packet["B"])
        self.assertTrue(packet["A"])
        self.assertTrue(packet["L"])
        self.assertTrue(packet["R"])
        self.assertTrue(packet["ZL"])
        self.assertTrue(packet["ZR"])
        self.assertTrue(packet["MINUS"])
        self.assertTrue(packet["PLUS"])
        self.assertTrue(packet["HOME"])
        self.assertTrue(packet["CAPTURE"])
        self.assertTrue(packet["DPAD_RIGHT"])
        self.assertTrue(packet["DPAD_DOWN"])

    def test_sdl3_backend_trigger_threshold_uses_fifty_percent(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        backend = Sdl3GamepadBackend()

        self.assertFalse(backend._trigger_pressed(16383))
        self.assertTrue(backend._trigger_pressed(16384))

    def test_sdl3_backend_maps_touchpad_click_to_capture(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        fake_sdl3 = FakeSdl3Module(
            [
                FakeSdl3Gamepad(
                    instance_id=44,
                    name="DualSense",
                    buttons={
                        FakeSdl3Module.SDL_GAMEPAD_BUTTON_TOUCHPAD: True,
                    },
                )
            ]
        )
        backend = Sdl3GamepadBackend()
        backend._sdl3 = fake_sdl3

        providers = backend.list_providers()
        backend.claim(providers[0].provider_id, 0)
        packet = backend.poll()[providers[0].provider_id]

        self.assertTrue(packet["CAPTURE"])

    def test_sdl3_backend_reports_missing_runtime_once(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        backend = Sdl3GamepadBackend()
        backend._sdl3 = FakeSdl3MissingRuntime([])

        self.assertEqual(backend.list_providers(), [])
        first_error = backend.last_error
        self.assertIn("no SDL3 runtime library was found", first_error)
        self.assertEqual(backend.list_providers(), [])
        self.assertEqual(backend.last_error, first_error)

    def test_sdl3_backend_prefers_local_runtime_directory(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        backend = Sdl3GamepadBackend()
        local_runtime = Path("local-sdl3-runtime")

        with mock.patch.dict("os.environ", {}, clear=False):
            with mock.patch.object(
                Sdl3GamepadBackend,
                "_find_local_runtime_dir",
                return_value=local_runtime,
            ):
                backend._configure_local_runtime_path()

            self.assertEqual(os.environ["SDL_BINARY_PATH"], str(local_runtime))
            self.assertEqual(os.environ["SDL_DISABLE_METADATA"], "1")

    def test_sdl3_backend_drops_disconnected_gamepads(self):
        from nxbt.qt.input_backends.sdl3 import Sdl3GamepadBackend

        gamepad = FakeSdl3Gamepad(
            instance_id=33,
            name="Switch Pro Controller",
            connected=True,
        )
        fake_sdl3 = FakeSdl3Module([gamepad])
        backend = Sdl3GamepadBackend()
        backend._sdl3 = fake_sdl3

        providers = backend.list_providers()
        backend.claim(providers[0].provider_id, 0)
        gamepad.connected = False

        packets = backend.poll()

        self.assertEqual(packets, {})
        self.assertEqual(fake_sdl3.closed, [33])


if __name__ == "__main__":
    unittest.main()
