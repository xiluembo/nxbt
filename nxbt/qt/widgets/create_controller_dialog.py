from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .controller_preview import ControllerPreviewWidget


class CreateControllerDialog(QDialog):
    def __init__(self, *, adapters, saved_addresses, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Pro Controller")
        self._body_color = (218, 218, 218)
        self._button_color = (25, 31, 40)

        outer_layout = QVBoxLayout(self)
        content_layout = QHBoxLayout()
        outer_layout.addLayout(content_layout)

        form_group = QGroupBox("Controller Setup", self)
        form_layout = QFormLayout(form_group)
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self.adapter_combo = QComboBox(self)
        for adapter in adapters:
            self.adapter_combo.addItem(adapter, adapter)
        form_layout.addRow("Bluetooth Adapter", self.adapter_combo)

        self.reconnect_combo = QComboBox(self)
        self.reconnect_combo.addItem("Pair New Switch", None)
        for address in saved_addresses:
            self.reconnect_combo.addItem(f"Reconnect to {address}", address)
        form_layout.addRow("Connection Mode", self.reconnect_combo)

        self.body_button = QPushButton("Choose Body Color", self)
        self.body_button.clicked.connect(self._choose_body_color)
        self.body_preview = self._create_color_swatch(self._body_color)
        form_layout.addRow(
            "Body Color",
            self._create_button_row(self.body_button, self.body_preview),
        )

        self.button_button = QPushButton("Choose Button Color", self)
        self.button_button.clicked.connect(self._choose_button_color)
        self.button_preview = self._create_color_swatch(self._button_color)
        form_layout.addRow(
            "Button Color",
            self._create_button_row(self.button_button, self.button_preview),
        )

        content_layout.addWidget(form_group, 1)

        preview_group = QGroupBox("Preview", self)
        preview_layout = QVBoxLayout(preview_group)
        self.preview = ControllerPreviewWidget(self)
        self.preview.set_colors(self._body_color, self._button_color)
        preview_layout.addWidget(self.preview)
        helper_label = QLabel(
            "The desktop UI currently creates Pro Controllers only.",
            self,
        )
        helper_label.setWordWrap(True)
        preview_layout.addWidget(helper_label)
        content_layout.addWidget(preview_group, 1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        outer_layout.addWidget(self.button_box)
        self.resize(840, 420)

    def selected_adapter(self) -> str:
        return self.adapter_combo.currentData()

    def reconnect_target(self):
        return self.reconnect_combo.currentData()

    def body_color(self):
        return self._body_color

    def button_color(self):
        return self._button_color

    def _choose_body_color(self) -> None:
        self._pick_color("Choose Body Color", "_body_color", self.body_preview)

    def _choose_button_color(self) -> None:
        self._pick_color("Choose Button Color", "_button_color", self.button_preview)

    def _pick_color(self, title: str, attribute: str, preview: QLabel) -> None:
        initial = QColor(*getattr(self, attribute))
        color = QColorDialog.getColor(initial, self, title)
        if not color.isValid():
            return
        rgb = (color.red(), color.green(), color.blue())
        setattr(self, attribute, rgb)
        preview.setStyleSheet(self._swatch_stylesheet(rgb))
        self.preview.set_colors(self._body_color, self._button_color)

    @staticmethod
    def _create_button_row(button: QPushButton, preview: QLabel) -> QWidget:
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(button, 0, 0)
        layout.addWidget(preview, 0, 1)
        return container

    @staticmethod
    def _create_color_swatch(rgb):
        swatch = QLabel()
        swatch.setFixedSize(28, 28)
        swatch.setStyleSheet(CreateControllerDialog._swatch_stylesheet(rgb))
        return swatch

    @staticmethod
    def _swatch_stylesheet(rgb):
        return (
            "border-radius: 6px;"
            "border: 1px solid #1a1f28;"
            f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});"
        )
