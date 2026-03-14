from .nxbt import Buttons
from .nxbt import JOYCON_L
from .nxbt import JOYCON_R
from .nxbt import Nxbt
from .nxbt import PRO_CONTROLLER
from .nxbt import Sticks
from .controller import Controller
from .controller import ControllerProtocol
from .controller import ControllerTypes
from .controller import SwitchReportParser
from .controller import SwitchResponses

__all__ = [
    "Buttons",
    "Controller",
    "ControllerProtocol",
    "ControllerServer",
    "ControllerTypes",
    "JOYCON_L",
    "JOYCON_R",
    "Nxbt",
    "PRO_CONTROLLER",
    "Sticks",
    "SwitchReportParser",
    "SwitchResponses",
]

_BLUEZ_EXPORTS = {
    "ADAPTER_INTERFACE",
    "BlueZ",
    "DEVICE_INTERFACE",
    "PROFILEMANAGER_INTERFACE",
    "SERVICE_NAME",
    "clean_sdp_records",
    "find_devices_by_alias",
    "find_objects",
    "replace_mac_addresses",
    "toggle_clean_bluez",
}


def __getattr__(name):
    if name == "ControllerServer":
        from .controller import ControllerServer

        return ControllerServer
    if name in _BLUEZ_EXPORTS:
        from . import bluez as bluez_module

        return getattr(bluez_module, name)
    raise AttributeError(f"module 'nxbt' has no attribute '{name}'")
