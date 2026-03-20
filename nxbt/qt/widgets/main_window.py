from __future__ import annotations

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..controller_manager import ControllerManager
from ..input_backends.manager import InputBackendManager
from ..input_packets import clone_packet, packets_equal
from .create_controller_dialog import CreateControllerDialog
from .session_card import SessionCard


class MainWindow(QMainWindow):
    INPUT_POLL_INTERVAL_MS = 4
    STATE_REFRESH_INTERVAL_MS = 200
    PROVIDER_REFRESH_INTERVAL_MS = 3000

    def __init__(
        self,
        *,
        controller_manager: ControllerManager,
        input_manager: InputBackendManager,
    ):
        super().__init__()
        self.controller_manager = controller_manager
        self.input_manager = input_manager
        self._session_cards: dict[int, SessionCard] = {}
        self._last_packets: dict[int, dict] = {}

        self.setWindowTitle("NXBT Desktop")
        self.resize(1400, 960)
        self._build_ui()
        self._build_timers()
        QApplication.instance().installEventFilter(self)
        self._refresh_provider_choices()
        self._refresh_sessions()
        self._refresh_status()

    def closeEvent(self, event: QCloseEvent) -> None:
        QApplication.instance().removeEventFilter(self)
        for timer in (self.input_timer, self.state_timer, self.provider_timer):
            timer.stop()
        self.input_manager.shutdown()
        self.controller_manager.shutdown()
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            if event.isAutoRepeat() or self._should_ignore_keyboard_capture():
                return False
            token = self._key_event_to_token(event)
            if token is None:
                return False
            if event.type() == QEvent.Type.KeyPress:
                handled = self.input_manager.handle_key_press(token)
            else:
                handled = self.input_manager.handle_key_release(token)
            if handled:
                # Flush keyboard changes immediately so short taps are not lost
                # between timer ticks on the Qt event loop.
                self._dispatch_input_packets()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)

        self.header_label = QLabel(self)
        self.header_label.setObjectName("headerLabel")
        self.header_label.setWordWrap(True)
        root_layout.addWidget(self.header_label)

        self.create_button = QPushButton("Create Pro Controller", self)
        self.create_button.clicked.connect(self._open_create_dialog)
        root_layout.addWidget(self.create_button)

        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)
        root_layout.addWidget(self.warning_label)

        self.adapter_count_label = QLabel(self)
        self.adapter_count_label.setWordWrap(True)
        root_layout.addWidget(self.adapter_count_label)

        self.empty_state_label = QLabel(
            "No controller sessions are active. Create a controller to begin.",
            self,
        )
        self.empty_state_label.setWordWrap(True)
        root_layout.addWidget(self.empty_state_label)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.session_container = QWidget(self)
        self.session_layout = QGridLayout(self.session_container)
        self.session_layout.setContentsMargins(0, 0, 0, 0)
        self.session_layout.setHorizontalSpacing(10)
        self.session_layout.setVerticalSpacing(10)
        self.scroll_area.setWidget(self.session_container)
        root_layout.addWidget(self.scroll_area, 1)

        status_bar = QStatusBar(self)
        self.status_text = QLabel(self)
        status_bar.addPermanentWidget(self.status_text, 1)
        self.setStatusBar(status_bar)

        self.setStyleSheet(
            """
            QMainWindow { background: #1a1f28; }
            QWidget { color: #d9dada; font-family: Segoe UI, Helvetica, Arial, sans-serif; }
            QPushButton {
                background: #d9dada;
                color: #1a1f28;
                padding: 7px 10px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:disabled {
                background: #647f96;
                color: #d9dada;
            }
            QGroupBox, #sessionCard {
                background: #2c3544;
                border: 1px solid #3a4759;
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QComboBox, QPlainTextEdit {
                background: #10151d;
                border: 1px solid #3a4759;
                border-radius: 6px;
                padding: 4px;
            }
            QLabel#headerLabel {
                font-size: 16px;
                font-weight: 700;
            }
            """
        )

    def _build_timers(self) -> None:
        self.input_timer = QTimer(self)
        self.input_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.input_timer.timeout.connect(self._dispatch_input_packets)
        self.input_timer.start(self.INPUT_POLL_INTERVAL_MS)

        self.state_timer = QTimer(self)
        self.state_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.state_timer.timeout.connect(self._refresh_sessions)
        self.state_timer.start(self.STATE_REFRESH_INTERVAL_MS)

        self.provider_timer = QTimer(self)
        self.provider_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.provider_timer.timeout.connect(self._refresh_provider_choices)
        self.provider_timer.start(self.PROVIDER_REFRESH_INTERVAL_MS)

    def _open_create_dialog(self) -> None:
        adapters = self.controller_manager.get_free_adapters(refresh=True)
        if not adapters:
            QMessageBox.information(
                self,
                "No Free Adapters",
                "No free Bluetooth adapters are available for another controller.",
            )
            return

        dialog = CreateControllerDialog(
            adapters=adapters,
            saved_addresses_by_adapter=(
                self.controller_manager.get_saved_switch_addresses_by_adapter(adapters)
            ),
            saved_metadata_by_adapter=(
                self.controller_manager.get_saved_switch_metadata_by_adapter(adapters)
            ),
            forget_pairing_callback=self.controller_manager.forget_saved_switch,
            parent=self,
        )
        if dialog.exec() == dialog.DialogCode.Accepted:
            try:
                session = self.controller_manager.create_session(
                    adapter_path=dialog.selected_adapter(),
                    body_color=dialog.body_color(),
                    button_color=dialog.button_color(),
                    reconnect_target=dialog.reconnect_target(),
                )
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Unable to Create Controller",
                    str(exc),
                )
                return
            self._ensure_session_card(session)
            self._refresh_provider_choices()
            self._refresh_sessions()

    def _ensure_session_card(self, session) -> SessionCard:
        card = self._session_cards.get(session.controller_index)
        if card is not None:
            return card
        card = SessionCard(session, self)
        card.provider_changed.connect(self._assign_provider)
        card.run_macro_requested.connect(self._run_macro)
        card.clear_macro_requested.connect(self._clear_macros)
        card.remove_requested.connect(self._remove_session)
        self._session_cards[session.controller_index] = card
        self._relayout_session_cards()
        return card

    def _refresh_provider_choices(self) -> None:
        self.input_manager.refresh_providers()
        for session in self.controller_manager.list_sessions():
            card = self._ensure_session_card(session)
            card.set_provider_choices(
                self.input_manager.list_assignable_providers(session.controller_index),
                self.input_manager.assigned_provider_id(session.controller_index),
            )
        self._refresh_status()

    def _refresh_sessions(self) -> None:
        sessions = self.controller_manager.refresh_sessions()
        active_indices = {session.controller_index for session in sessions}
        for controller_index in list(self._session_cards):
            if controller_index not in active_indices:
                card = self._session_cards.pop(controller_index)
                card.setParent(None)
                card.deleteLater()
                self._last_packets.pop(controller_index, None)
                self._relayout_session_cards()

        for session in sessions:
            card = self._ensure_session_card(session)
            card.update_session(session)

        self.empty_state_label.setVisible(len(sessions) == 0)
        self.create_button.setEnabled(bool(self.controller_manager.get_free_adapters()))
        self._refresh_status()

    def _refresh_status(self) -> None:
        backend_name = self.controller_manager.backend_status.get("name", "unknown")
        self.header_label.setText(f"Backend: {backend_name}")
        free_adapters = self.controller_manager.get_free_adapters()
        self.adapter_count_label.setText(
            f"Free Bluetooth adapters: {len(free_adapters)}"
        )
        warnings = self._collect_warnings()
        if warnings:
            self.warning_label.setText("\n".join(warnings))
            self.warning_label.show()
        else:
            self.warning_label.hide()
        self.status_text.setText(
            "Keyboard input is captured while the window is focused and no text field is active."
        )

    def _dispatch_input_packets(self) -> None:
        for controller_index, packet in self.input_manager.poll_packets().items():
            session = self.controller_manager.get_session(controller_index)
            if session is None or session.state == "crashed":
                continue
            previous_packet = self._last_packets.get(controller_index)
            if previous_packet is not None and packets_equal(previous_packet, packet):
                continue
            try:
                self.controller_manager.send_input(controller_index, packet)
            except Exception:
                continue
            self._last_packets[controller_index] = clone_packet(packet)
            card = self._session_cards.get(controller_index)
            if card is not None:
                card.preview.set_packet(packet)

    def _assign_provider(self, controller_index: int, provider_id: str | None) -> None:
        try:
            self.input_manager.assign_provider(controller_index, provider_id)
            self.controller_manager.update_provider_assignment(
                controller_index,
                provider_id,
            )
            if provider_id is None:
                self.controller_manager.reset_input(controller_index)
                self._last_packets.pop(controller_index, None)
        except Exception as exc:
            QMessageBox.warning(self, "Unable to Assign Input", str(exc))
        self._refresh_provider_choices()
        self._refresh_sessions()

    def _run_macro(self, controller_index: int, macro_text: str) -> None:
        if not macro_text:
            QMessageBox.information(
                self,
                "Macro Required",
                "Enter a macro before trying to run it.",
            )
            return
        try:
            self.controller_manager.run_macro(controller_index, macro_text.upper())
        except Exception as exc:
            QMessageBox.critical(self, "Unable to Run Macro", str(exc))
        self._refresh_sessions()

    def _clear_macros(self, controller_index: int) -> None:
        try:
            self.controller_manager.clear_macros(controller_index)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to Clear Macros", str(exc))
        self._refresh_sessions()

    def _remove_session(self, controller_index: int) -> None:
        self.input_manager.release_controller(controller_index)
        try:
            self.controller_manager.remove_session(controller_index)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to Remove Controller", str(exc))
        self._last_packets.pop(controller_index, None)
        self.controller_manager.refresh_available_adapters()
        self._refresh_provider_choices()
        self._refresh_sessions()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_session_cards()

    def _should_ignore_keyboard_capture(self) -> bool:
        focus_widget = self.focusWidget()
        if focus_widget is None:
            return False
        ignored_types = (
            QLineEdit,
            QTextEdit,
            QPlainTextEdit,
            QComboBox,
            QAbstractSpinBox,
            QAbstractButton,
        )
        return isinstance(focus_widget, ignored_types)

    @staticmethod
    def _key_event_to_token(event) -> str | None:
        key = event.key()
        special_keys = {
            Qt.Key.Key_Up: "UP",
            Qt.Key.Key_Down: "DOWN",
            Qt.Key.Key_Left: "LEFT",
            Qt.Key.Key_Right: "RIGHT",
        }
        if key in special_keys:
            return special_keys[key]

        text = event.text()
        if not text:
            return None
        token = text.upper()
        if token in {"[", "]"}:
            return token
        if token.isalnum():
            return token
        return None

    def _relayout_session_cards(self) -> None:
        while self.session_layout.count():
            item = self.session_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.session_container)

        cards = [self._session_cards[index] for index in sorted(self._session_cards)]
        if not cards:
            return

        columns = self._session_columns()
        for index, card in enumerate(cards):
            row = index // columns
            column = index % columns
            self.session_layout.addWidget(card, row, column)

        for column in range(columns):
            self.session_layout.setColumnStretch(column, 1)

    def _session_columns(self) -> int:
        width = self.scroll_area.viewport().width()
        if width >= 1500:
            return 3
        if width >= 900:
            return 2
        return 1

    def _collect_warnings(self) -> list[str]:
        warnings = []
        backend_status = self.controller_manager.backend_status
        backend_message = backend_status.get("message", "")
        if backend_message and not backend_status.get("available", True):
            warnings.append(backend_message)

        for descriptor in backend_status.get("unavailable_adapter_details", []):
            adapter_id = descriptor.get("id", "unknown")
            probe_error = descriptor.get("probe_error", "")
            if probe_error:
                warnings.append(f"{adapter_id}: {probe_error}")

        warnings.extend(self.input_manager.get_warnings())
        return warnings
