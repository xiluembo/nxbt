from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QWidget

from ..input_packets import clone_packet, create_input_packet
from ..svg_utils import recolor_pro_controller_svg


class ControllerPreviewWidget(QWidget):
    SVG_SIZE = (460.11, 316.67)
    INDICATOR_COLOR = QColor("#647f96")
    INDICATOR_VERTICAL_OFFSET_PERCENT = 1.8
    BUTTON_INDICATORS = {
        "DPAD_UP": {
            "left": 30.7,
            "top": 36.0,
            "size": 0.06,
            "shape": "square",
            "offset_y": -0.8,
        },
        "DPAD_LEFT": {
            "left": 25.8,
            "top": 45.2,
            "size": 0.06,
            "shape": "square",
            "offset_y": -0.8,
        },
        "DPAD_RIGHT": {
            "left": 36.8,
            "top": 44.4,
            "size": 0.06,
            "shape": "square",
            "offset_y": -0.8,
        },
        "DPAD_DOWN": {
            "left": 31.3,
            "top": 52.4,
            "size": 0.06,
            "shape": "square",
            "offset_y": -0.8,
        },
        "HOME": {"left": 54.0, "top": 24.0, "size": 0.06, "shape": "circle"},
        "CAPTURE": {"left": 40.0, "top": 24.0, "size": 0.06, "shape": "circle"},
        "MINUS": {"left": 35.0, "top": 13.0, "size": 0.06, "shape": "circle"},
        "PLUS": {"left": 59.0, "top": 12.0, "size": 0.06, "shape": "circle"},
        "B": {"left": 72.0, "top": 32.0, "size": 0.08, "shape": "circle"},
        "A": {"left": 80.0, "top": 22.0, "size": 0.08, "shape": "circle"},
        "Y": {"left": 64.0, "top": 22.0, "size": 0.08, "shape": "circle"},
        "X": {"left": 72.0, "top": 12.0, "size": 0.08, "shape": "circle"},
        "L": {"left": 10.0, "top": 2.0, "size": 0.06, "shape": "circle"},
        "ZL": {"left": 17.0, "top": -2.0, "size": 0.06, "shape": "circle"},
        "R": {"left": 84.0, "top": 2.0, "size": 0.06, "shape": "circle"},
        "ZR": {"left": 77.0, "top": -2.0, "size": 0.06, "shape": "circle"},
    }
    STICK_INDICATORS = {
        "L_STICK": {
            "min_x": 15.5,
            "max_x": 23.0,
            "min_y": 18.0,
            "max_y": 29.0,
            "size": 0.06,
        },
        "R_STICK": {
            "min_x": 56.0,
            "max_x": 63.5,
            "min_y": 38.125,
            "max_y": 50.0,
            "size": 0.06,
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = QSvgRenderer(self)
        self._packet = create_input_packet()
        self._body_color = (218, 218, 218)
        self._button_color = (25, 31, 40)
        self._svg_template = self._load_svg_template()
        self.setMinimumSize(180, 124)
        self.setMaximumHeight(180)
        self.set_colors(self._body_color, self._button_color)

    def sizeHint(self) -> QSize:
        return QSize(220, 152)

    def set_colors(self, body_color, button_color) -> None:
        self._body_color = tuple(body_color)
        self._button_color = tuple(button_color)
        svg_text = recolor_pro_controller_svg(
            self._svg_template,
            body_color=self._body_color,
            button_color=self._button_color,
        )
        self._renderer.load(QByteArray(svg_text.encode("utf-8")))
        self.update()

    def set_packet(self, packet) -> None:
        self._packet = clone_packet(packet)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        target = self._target_rect()
        self._renderer.render(painter, target)
        self._draw_button_indicators(painter, target)
        self._draw_stick_indicators(painter, target)

    def _draw_button_indicators(self, painter: QPainter, target: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.INDICATOR_COLOR)
        for button_name, metadata in self.BUTTON_INDICATORS.items():
            if not self._packet.get(button_name):
                continue
            indicator_rect = self._indicator_rect(
                target,
                left_percent=metadata["left"],
                top_percent=metadata["top"],
                size_ratio=metadata["size"],
                offset_x=metadata.get("offset_x", 0.0),
                offset_y=metadata.get("offset_y", 0.0),
            )
            if metadata["shape"] == "square":
                painter.drawRoundedRect(indicator_rect, 3.0, 3.0)
            else:
                painter.drawEllipse(indicator_rect)

    def _draw_stick_indicators(self, painter: QPainter, target: QRectF) -> None:
        for stick_name, metadata in self.STICK_INDICATORS.items():
            stick_packet = self._packet[stick_name]
            x_ratio = (stick_packet["X_VALUE"] + 100) / 200
            y_ratio = (stick_packet["Y_VALUE"] + 100) / 200
            left_percent = metadata["min_x"] + (
                x_ratio * (metadata["max_x"] - metadata["min_x"])
            )
            top_percent = metadata["max_y"] - (
                y_ratio * (metadata["max_y"] - metadata["min_y"])
            )
            indicator_rect = self._indicator_rect(
                target,
                left_percent=left_percent,
                top_percent=top_percent,
                size_ratio=metadata["size"],
                offset_x=metadata.get("offset_x", 0.0),
                offset_y=metadata.get("offset_y", 0.0),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.INDICATOR_COLOR)
            painter.drawEllipse(indicator_rect)
            if stick_packet["PRESSED"]:
                pressed_pen = QPen(QColor("#d9dada"))
                pressed_pen.setWidth(2)
                painter.setPen(pressed_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(indicator_rect.adjusted(-2, -2, 2, 2))

    @staticmethod
    def _indicator_rect(
        target: QRectF,
        *,
        left_percent: float,
        top_percent: float,
        size_ratio: float,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> QRectF:
        size = target.width() * size_ratio
        return QRectF(
            target.left()
            + (((left_percent + offset_x) / 100.0) * target.width()),
            target.top()
            + (
                (
                    top_percent
                    + ControllerPreviewWidget.INDICATOR_VERTICAL_OFFSET_PERCENT
                    + offset_y
                )
                / 100.0
            )
            * target.height(),
            size,
            size,
        )

    def _target_rect(self) -> QRectF:
        svg_width, svg_height = self.SVG_SIZE
        bounds = QRectF(self.rect())
        scale = min(bounds.width() / svg_width, bounds.height() / svg_height)
        width = svg_width * scale
        height = svg_height * scale
        return QRectF(
            (bounds.width() - width) / 2.0,
            (bounds.height() - height) / 2.0,
            width,
            height,
        )

    @staticmethod
    def _load_svg_template() -> str:
        svg_path = (
            Path(__file__).resolve().parents[2]
            / "web"
            / "static"
            / "procon.svg"
        )
        return svg_path.read_text(encoding="utf-8")
