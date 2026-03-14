from .controller import ControllerTypes
from .controller import Controller
from .protocol import ControllerProtocol
from .protocol import SwitchReportParser
from .protocol import SwitchResponses

__all__ = [
    "Controller",
    "ControllerProtocol",
    "ControllerServer",
    "ControllerTypes",
    "SwitchReportParser",
    "SwitchResponses",
]


def __getattr__(name):
    if name == "ControllerServer":
        from .server import ControllerServer

        return ControllerServer
    raise AttributeError(f"module 'nxbt.controller' has no attribute '{name}'")
