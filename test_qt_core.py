import unittest

from nxbt.qt.controller_manager import ControllerManager
from nxbt.qt.input_backends.base import BaseInputBackend
from nxbt.qt.input_backends.keyboard import KeyboardInputBackend
from nxbt.qt.input_backends.manager import InputBackendManager
from nxbt.qt.models import InputProvider


class FakeNxbt:
    def __init__(self):
        self.created = []
        self.removed = []
        self.macros = []
        self.inputs = []
        self._controller_counter = 0
        self._state = {}

    def get_backend_status(self):
        return {"name": "fake"}

    def get_available_adapters(self):
        return ["adapter-0", "adapter-1"]

    def get_switch_addresses(self):
        return ["AA:BB:CC:DD:EE:FF"]

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


class FakeJoystick:
    def __init__(self, *, name, axes, buttons, hats):
        self._name = name
        self._axes = axes
        self._buttons = buttons
        self._hats = hats

    def get_name(self):
        return self._name

    def get_numaxes(self):
        return len(self._axes)

    def get_axis(self, index):
        return self._axes[index]

    def get_numbuttons(self):
        return len(self._buttons)

    def get_button(self, index):
        return self._buttons[index]

    def get_numhats(self):
        return len(self._hats)

    def get_hat(self, index):
        return self._hats[index]


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

    def test_pygame_backend_maps_xinput_layout(self):
        from nxbt.qt.input_backends.pygame import PygameGamepadBackend

        backend = PygameGamepadBackend()
        joystick = FakeJoystick(
            name="Xbox 360 Controller",
            axes=[0.25, -0.5, -0.75, 0.4, 0.9, 0.8],
            buttons=[
                1,  # B
                1,  # A
                0,  # Y
                0,  # X
                1,  # L
                1,  # R
                1,  # Start / Plus
                1,  # Select / Minus
                1,  # L3
                1,  # R3
                1,  # Guide / Home
            ],
            hats=[(1, -1)],
        )

        backend._trigger_axis_modes["gamepad:xinput"] = {4: "unsigned", 5: "unsigned"}
        packet = backend._read_joystick_packet("gamepad:xinput", joystick)

        self.assertTrue(packet["L_STICK"]["PRESSED"])
        self.assertTrue(packet["R_STICK"]["PRESSED"])
        self.assertTrue(packet["MINUS"])
        self.assertTrue(packet["PLUS"])
        self.assertTrue(packet["HOME"])
        self.assertTrue(packet["ZL"])
        self.assertTrue(packet["ZR"])
        self.assertTrue(packet["DPAD_RIGHT"])
        self.assertTrue(packet["DPAD_DOWN"])

    def test_pygame_backend_keeps_standard_button_layout(self):
        from nxbt.qt.input_backends.pygame import PygameGamepadBackend

        backend = PygameGamepadBackend()
        joystick = FakeJoystick(
            name="Generic USB Gamepad",
            axes=[0.0, 0.0, 0.0, 0.0],
            buttons=[
                0, 0, 0, 0, 0, 0,
                1,  # ZL
                1,  # ZR
                1,  # Plus
                1,  # Minus
                1,  # L3
                1,  # R3
                0, 0, 0, 0,
                1,  # Home
                1,  # Capture
            ],
            hats=[],
        )

        packet = backend._read_joystick_packet("gamepad:generic", joystick)

        self.assertTrue(packet["ZL"])
        self.assertTrue(packet["ZR"])
        self.assertTrue(packet["PLUS"])
        self.assertTrue(packet["MINUS"])
        self.assertTrue(packet["L_STICK"]["PRESSED"])
        self.assertTrue(packet["R_STICK"]["PRESSED"])
        self.assertTrue(packet["HOME"])
        self.assertTrue(packet["CAPTURE"])

    def test_xinput_signed_trigger_threshold_uses_fifty_percent(self):
        from nxbt.qt.input_backends.pygame import PygameGamepadBackend

        backend = PygameGamepadBackend()
        joystick = FakeJoystick(
            name="Xbox 360 Controller",
            axes=[0.0, 0.0, 0.0, 0.0, -1.0, -1.0],
            buttons=[0] * 11,
            hats=[],
        )
        backend._read_joystick_packet("gamepad:xinput", joystick)

        joystick = FakeJoystick(
            name="Xbox 360 Controller",
            axes=[0.0, 0.0, 0.0, 0.0, -0.25, 0.0],
            buttons=[0] * 11,
            hats=[],
        )
        packet = backend._read_joystick_packet("gamepad:xinput", joystick)
        self.assertFalse(packet["ZL"])
        self.assertTrue(packet["ZR"])

        joystick = FakeJoystick(
            name="Xbox 360 Controller",
            axes=[0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            buttons=[0] * 11,
            hats=[],
        )
        packet = backend._read_joystick_packet("gamepad:xinput", joystick)
        self.assertTrue(packet["ZL"])
        self.assertTrue(packet["ZR"])

    def test_xinput_unsigned_trigger_threshold_uses_fifty_percent(self):
        from nxbt.qt.input_backends.pygame import PygameGamepadBackend

        backend = PygameGamepadBackend()
        backend._trigger_axis_modes["gamepad:xinput"] = {4: "unsigned", 5: "unsigned"}
        joystick = FakeJoystick(
            name="Xbox 360 Controller",
            axes=[0.0, 0.0, 0.0, 0.0, 0.49, 0.5],
            buttons=[0] * 11,
            hats=[],
        )

        packet = backend._read_joystick_packet("gamepad:xinput", joystick)
        self.assertFalse(packet["ZL"])
        self.assertTrue(packet["ZR"])


if __name__ == "__main__":
    unittest.main()
