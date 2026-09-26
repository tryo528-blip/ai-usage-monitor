"""Shared palette and painters for the main window, cards, and tray icons.

The visual language has two independent channels:

* hue identifies the provider (Codex is always green, Claude always coral), and
* arc length shows how much quota is left, sweeping clockwise from 12 o'clock
  like a clock hand.

Severity only tints the number, so a glance answers "who" by color and
"how much" by length without the two signals fighting each other.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

BACKGROUND = "#0d1220"
SURFACE = "#151c2e"
SURFACE_HOVER = "#1c2540"
BORDER = "#232d45"
TRACK = "#262f47"
TEXT = "#eef3ff"
TEXT_MUTED = "#7f8cab"
TEXT_FAINT = "#56627f"

PROVIDER_ACCENTS: dict[str, str] = {
    "codex": "#3ddc97",
    "grok": "#c9d4e5",
    "claude": "#e07a5f",
    "antyg": "#a78bfa",
    "openrouter": "#56c8f5",
}
DEFAULT_ACCENT = "#8b93a7"


class AlertLevel(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    MUTED = "muted"


LEVEL_TEXT_COLORS: dict[AlertLevel, str] = {
    AlertLevel.OK: TEXT,
    AlertLevel.WARNING: "#ffc857",
    AlertLevel.CRITICAL: "#ff6b73",
    AlertLevel.MUTED: TEXT_MUTED,
}

# Same thresholds as services.status_policy: 80% used warns, 95% used is critical.
WARNING_REMAINING_PERCENT = 20.0
CRITICAL_REMAINING_PERCENT = 5.0


def accent_for(provider_id: str) -> str:
    base = provider_id.split("_", 1)[0]
    return PROVIDER_ACCENTS.get(base, DEFAULT_ACCENT)


def level_for_remaining(remaining_percent: float) -> AlertLevel:
    if remaining_percent <= CRITICAL_REMAINING_PERCENT:
        return AlertLevel.CRITICAL
    if remaining_percent <= WARNING_REMAINING_PERCENT:
        return AlertLevel.WARNING
    return AlertLevel.OK


def draw_ring(
    painter: QPainter,
    rect: QRectF,
    fraction: float | None,
    accent: str,
    *,
    width: float,
    track: str = TRACK,
) -> None:
    """Draw a track circle and a clockwise arc covering ``fraction`` of it.

    ``fraction`` is clamped to [0, 1]. ``None`` means "no measurement" and is
    drawn as a dotted track so an unknown value never looks like an empty tank.
    """

    inset = width / 2
    ring = rect.adjusted(inset, inset, -inset, -inset)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    track_pen = QPen(QColor(track), width)
    track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    if fraction is None:
        track_pen.setStyle(Qt.PenStyle.DotLine)
    painter.setPen(track_pen)
    painter.drawEllipse(ring)
    if fraction is None:
        return

    fraction = max(0.0, min(1.0, fraction))
    if fraction <= 0:
        return
    arc_pen = QPen(QColor(accent), width)
    arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap if fraction < 1 else Qt.PenCapStyle.FlatCap)
    painter.setPen(arc_pen)
    # Qt angles are in 1/16 degree, counter-clockwise from 3 o'clock. Start at
    # 12 o'clock (90 degrees) and sweep negative (clockwise).
    painter.drawArc(ring, 90 * 16, -round(fraction * 360 * 16))


def _icon_from_path(path_builder, color: str, *, size: int = 32, stroke: float = 1.5) -> QIcon:
    icon = QIcon()
    for mode, alpha in ((QIcon.Mode.Normal, 200), (QIcon.Mode.Active, 255)):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen_color = QColor(color)
        pen_color.setAlpha(alpha)
        pen = QPen(pen_color, stroke)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.scale(size / 16, size / 16)
        painter.drawPath(path_builder())
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


def _refresh_path() -> QPainterPath:
    path = QPainterPath()
    rect = QRectF(3.5, 3.5, 9, 9)
    path.arcMoveTo(rect, 60)
    path.arcTo(rect, 60, 285)
    path.moveTo(QPointF(10.2, 2.4))
    path.lineTo(QPointF(10.8, 4.9))
    path.lineTo(QPointF(8.3, 5.5))
    return path


def _settings_path() -> QPainterPath:
    # Three sliders: a quiet, symmetric stand-in for a gear.
    path = QPainterPath()
    for y, knob in ((4.5, 10.5), (8.0, 5.5), (11.5, 9.0)):
        path.moveTo(3, y)
        path.lineTo(13, y)
        path.addEllipse(QPointF(knob, y), 1.2, 1.2)
    return path


def _minimize_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(4.5, 8)
    path.lineTo(11.5, 8)
    return path


def _close_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(5, 5)
    path.lineTo(11, 11)
    path.moveTo(11, 5)
    path.lineTo(5, 11)
    return path


def refresh_icon() -> QIcon:
    return _icon_from_path(_refresh_path, TEXT)


def settings_icon() -> QIcon:
    return _icon_from_path(_settings_path, TEXT, stroke=1.3)


def minimize_icon() -> QIcon:
    return _icon_from_path(_minimize_path, TEXT)


def close_icon() -> QIcon:
    return _icon_from_path(_close_path, TEXT)


def bold_font(base: QFont, point_size: float) -> QFont:
    font = QFont(base)
    font.setPointSizeF(point_size)
    font.setBold(True)
    return font
