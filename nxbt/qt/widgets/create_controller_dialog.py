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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .controller_preview import ControllerPreviewWidget


class CreateControllerDialog(QDialog):
    DEFAULT_BODY_COLOR = (218, 218, 218)
    DEFAULT_BUTTON_COLOR = (25, 31, 40)

    def __init__(
        self,
        *,
        adapters,
        saved_metadata_by_adapter,
        forget_pairing_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Create Pro Controller")
        self._body_color = self.DEFAULT_BODY_COLOR
        self._button_color = self.DEFAULT_BUTTON_COLOR
        self._forget_pairing_callback = forget_pairing_callback
        self._saved_metadata_by_adapter = {
            adapter: dict(addresses)
            for adapter, addresses in saved_metadata_by_adapter.items()
        }

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
        self.adapter_combo.currentIndexChanged.connect(self._refresh_reconnect_options)
        form_layout.addRow("Bluetooth Adapter", self.adapter_combo)

        self.reconnect_combo = QComboBox(self)
        self.reconnect_combo.currentIndexChanged.connect(self._apply_saved_colors)
        self.forget_pairing_button = QPushButton("Forget Pairing", self)
        self.forget_pairing_button.clicked.connect(self._forget_selected_pairing)
        form_layout.addRow(
            "Connection Mode",
            self._create_button_row(self.reconnect_combo, self.forget_pairing_button),
        )

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
        self._refresh_reconnect_options()

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

    def _refresh_reconnect_options(self) -> None:
        selected_address = self.reconnect_combo.currentData()
        self.reconnect_combo.blockSignals(True)
        self.reconnect_combo.clear()
        self.reconnect_combo.addItem("Pair New Switch", None)

        adapter = self.selected_adapter()
        for address in self._saved_metadata_by_adapter.get(adapter, {}).keys():
            self.reconnect_combo.addItem(f"Reconnect to {address}", address)

        restored_index = self.reconnect_combo.findData(selected_address)
        if restored_index >= 0:
            self.reconnect_combo.setCurrentIndex(restored_index)
        self.reconnect_combo.blockSignals(False)
        self._apply_saved_colors()

    def _apply_saved_colors(self) -> None:
        adapter = self.selected_adapter()
        address = self.reconnect_combo.currentData()
        metadata = {}
        if address is not None:
            metadata = self._saved_metadata_by_adapter.get(adapter, {}).get(address, {})

        body_color = metadata.get("colour_body", self.DEFAULT_BODY_COLOR)
        button_color = metadata.get("colour_buttons", self.DEFAULT_BUTTON_COLOR)
        self._set_colors(body_color, button_color)
        self._update_forget_pairing_button()

    def _update_forget_pairing_button(self) -> None:
        self.forget_pairing_button.setEnabled(
            self._forget_pairing_callback is not None
            and self.reconnect_combo.currentData() is not None
        )

    def _forget_selected_pairing(self) -> None:
        if self._forget_pairing_callback is None:
            return

        adapter = self.selected_adapter()
        address = self.reconnect_combo.currentData()
        if adapter is None or address is None:
            return

        answer = QMessageBox.question(
            self,
            "Forget Pairing",
            (
                f"Forget the saved pairing for {address} on adapter {adapter}?\n\n"
                "This only removes the saved pairing for the selected adapter."
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._forget_pairing_callback(adapter, address)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to Forget Pairing", str(exc))
            return

        self._saved_metadata_by_adapter.get(adapter, {}).pop(address, None)
        self._refresh_reconnect_options()

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

    def _set_colors(self, body_color, button_color) -> None:
        self._body_color = tuple(body_color)
        self._button_color = tuple(button_color)
        self.body_preview.setStyleSheet(self._swatch_stylesheet(self._body_color))
        self.button_preview.setStyleSheet(self._swatch_stylesheet(self._button_color))
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
