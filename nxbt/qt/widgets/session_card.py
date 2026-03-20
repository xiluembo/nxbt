from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import SessionRecord
from .controller_preview import ControllerPreviewWidget


class SessionCard(QWidget):
    provider_changed = pyqtSignal(int, object)
    run_macro_requested = pyqtSignal(int, str)
    clear_macro_requested = pyqtSignal(int)
    remove_requested = pyqtSignal(int)

    def __init__(self, session: SessionRecord, parent=None):
        super().__init__(parent)
        self.session = session
        self.setObjectName("sessionCard")
        self.setMinimumWidth(480)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(f"Controller #{session.controller_index}", self)
        self.state_label = QLabel(self)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self._emit_remove_requested)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.state_label)
        header_layout.addWidget(self.remove_button)
        root_layout.addLayout(header_layout)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        preview_group = QGroupBox("Live Preview", self)
        preview_group_layout = QVBoxLayout(preview_group)
        preview_group_layout.setContentsMargins(8, 12, 8, 8)
        self.preview = ControllerPreviewWidget(self)
        self.preview.set_colors(session.body_color, session.button_color)
        preview_group_layout.addWidget(self.preview)
        self.motion_label = QLabel(self)
        self.motion_label.setWordWrap(True)
        preview_group_layout.addWidget(self.motion_label)
        self._set_motion_status("Motion Sensor: Default IMU", False)
        preview_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        content_layout.addWidget(preview_group, 0)
        content_layout.setAlignment(preview_group, Qt.AlignmentFlag.AlignTop)

        controls_container = QWidget(self)
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        info_group = QGroupBox("Session Details", self)
        info_layout = QGridLayout(info_group)
        info_layout.setContentsMargins(8, 12, 8, 8)
        self.adapter_label = QLabel(self)
        self.adapter_label.setWordWrap(True)
        self.connection_label = QLabel(self)
        self.connection_label.setWordWrap(True)
        self.input_combo = QComboBox(self)
        self.input_combo.currentIndexChanged.connect(self._emit_provider_changed)
        self.provider_note = QLabel(self)
        self.provider_note.setWordWrap(True)
        self.provider_note.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        info_layout.addWidget(QLabel("Adapter", self), 0, 0)
        info_layout.addWidget(self.adapter_label, 0, 1)
        info_layout.addWidget(QLabel("Connection", self), 1, 0)
        info_layout.addWidget(self.connection_label, 1, 1)
        info_layout.addWidget(QLabel("Input Backend", self), 2, 0)
        info_layout.addWidget(self.input_combo, 2, 1)
        info_layout.addWidget(self.provider_note, 3, 0, 1, 2)
        controls_layout.addWidget(info_group)

        macro_group = QGroupBox("Macros", self)
        macro_layout = QVBoxLayout(macro_group)
        macro_layout.setContentsMargins(8, 12, 8, 8)
        macro_layout.setSpacing(6)
        self.macro_editor = QPlainTextEdit(self)
        self.macro_editor.setPlaceholderText("Type a macro using the NXBT macro syntax.")
        self.macro_editor.setMinimumHeight(84)
        self.macro_editor.setMaximumHeight(110)
        macro_font = self.macro_editor.font()
        macro_font.setFamily("Consolas")
        macro_font.setPointSize(max(macro_font.pointSize() - 1, 8))
        self.macro_editor.setFont(macro_font)
        macro_actions = QHBoxLayout()
        macro_actions.setContentsMargins(0, 0, 0, 0)
        self.run_macro_button = QPushButton("Run Macro", self)
        self.run_macro_button.clicked.connect(self._emit_run_macro_requested)
        self.clear_macro_button = QPushButton("Clear Macros", self)
        self.clear_macro_button.clicked.connect(self._emit_clear_macro_requested)
        macro_actions.addWidget(self.run_macro_button)
        macro_actions.addWidget(self.clear_macro_button)
        self.macro_status = QLabel(self)
        self.macro_status.setWordWrap(True)
        self.macro_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        macro_layout.addWidget(self.macro_editor)
        macro_layout.addLayout(macro_actions)
        macro_layout.addWidget(self.macro_status)
        controls_layout.addWidget(macro_group)

        controls_layout.addStretch(1)
        content_layout.addWidget(controls_container, 1)
        content_layout.setAlignment(controls_container, Qt.AlignmentFlag.AlignTop)

        root_layout.addLayout(content_layout)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        self.update_session(session)

    def update_session(self, session: SessionRecord) -> None:
        self.session = session
        self.title_label.setText(f"Controller #{session.controller_index}")
        self.state_label.setText(f"State: {session.state.title()}")
        self.adapter_label.setText(session.adapter_path)
        if session.reconnect_target is None:
            self.connection_label.setText("New Pairing")
        elif isinstance(session.reconnect_target, list):
            self.connection_label.setText("Reconnect to saved Switches")
        else:
            self.connection_label.setText(f"Reconnect to {session.reconnect_target}")
        self.preview.set_colors(session.body_color, session.button_color)
        self.preview.set_packet(session.last_input_packet)
        self.run_macro_button.setEnabled(session.state == "connected")
        if session.errors:
            self.macro_status.setText(session.errors)
        elif session.current_macro_id:
            self.macro_status.setText("A macro is currently running.")
        else:
            self.macro_status.setText("Direct input overrides macros while active.")

    def set_provider_choices(self, providers, assigned_provider_id):
        provider_map = {provider.provider_id: provider for provider in providers}
        self.input_combo.blockSignals(True)
        self.input_combo.clear()
        self.input_combo.addItem("No Input Provider", None)
        for provider in providers:
            label = provider.display_name
            if provider.profile_label:
                label = f"{label} [{provider.profile_label}]"
            self.input_combo.addItem(label, provider.provider_id)
        index = self.input_combo.findData(assigned_provider_id)
        self.input_combo.setCurrentIndex(max(index, 0))
        self.input_combo.blockSignals(False)

        if assigned_provider_id is None:
            self.provider_note.setText(
                "Assign a unique keyboard or gamepad provider."
            )
            self._set_motion_status("Motion Sensor: Default IMU", False)
        else:
            provider = provider_map.get(assigned_provider_id)
            if provider is not None:
                if provider.details:
                    self.provider_note.setText(provider.details)
                else:
                    self.provider_note.setText(
                        "This input provider is reserved for this controller."
                    )
                self._set_motion_status(
                    provider.motion_status,
                    provider.motion_available,
                )
            else:
                self.provider_note.setText(
                    "This input provider is reserved for this controller."
                )
                self._set_motion_status("Motion Sensor: Default IMU", False)

    def _set_motion_status(self, status: str, active: bool) -> None:
        color = "#84c97c" if active else "#9aa5b1"
        self.motion_label.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.motion_label.setText(status)

    def _emit_provider_changed(self) -> None:
        provider_id = self.input_combo.currentData()
        self.provider_changed.emit(self.session.controller_index, provider_id)

    def _emit_run_macro_requested(self) -> None:
        macro_text = self.macro_editor.toPlainText().strip()
        self.run_macro_requested.emit(self.session.controller_index, macro_text)

    def _emit_clear_macro_requested(self) -> None:
        self.clear_macro_requested.emit(self.session.controller_index)

    def _emit_remove_requested(self) -> None:
        self.remove_requested.emit(self.session.controller_index)
