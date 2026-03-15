from __future__ import annotations

import sys
import traceback


def start_qt_app():
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from .controller_manager import ControllerManager
    from .input_backends.manager import InputBackendManager
    from .widgets.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NXBT Desktop")

    try:
        controller_manager = ControllerManager()
        input_manager = InputBackendManager()
        window = MainWindow(
            controller_manager=controller_manager,
            input_manager=input_manager,
        )
    except Exception as exc:
        QMessageBox.critical(
            None,
            "NXBT Desktop Startup Failed",
            f"{exc}\n\n{traceback.format_exc()}",
        )
        raise

    window.show()
    return app.exec()
