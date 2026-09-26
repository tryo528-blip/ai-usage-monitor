"""Up to three live gauges in the Windows taskbar notification area.

Each pinned provider gets its own tray icon: a dark disc (readable on light and
dark taskbars), a ring in the provider's color whose arc is the remaining
quota, and the remaining number in the middle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme
from .theme import AlertLevel

if TYPE_CHECKING:
    from .provider_card import ProviderCard

# Windows asks for 16px at 100% scaling and up to 32px at 200%. Painting each
# size separately keeps the digits sharp instead of letting Windows resample.
_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64)


def render_tray_pixmap(
    size: int,
    value: str,
    fraction: float | None,
    accent: str,
    level: AlertLevel,
) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(0, 0, size, size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.BACKGROUND))
    painter.drawEllipse(rect.adjusted(0.5, 0.5, -0.5, -0.5))

    ring_width = max(1.6, size * 0.12)
    ring_rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    theme.draw_ring(painter, ring_rect, fraction, accent, width=ring_width)

    if len(value) > 2:
        # "100" does not fit in 16px; a full ring with a center dot says it.
        dot = size * 0.16
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.LEVEL_TEXT_COLORS[level]))
        painter.drawEllipse(rect.center(), dot, dot)
    else:
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(7, round(size * (0.62 if len(value) == 1 else 0.52))))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -size * 0.03)
        painter.setFont(font)
        painter.setPen(QColor(theme.LEVEL_TEXT_COLORS[level]))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, value)
    painter.end()
    return pixmap


def render_tray_icon(
    value: str,
    fraction: float | None,
    accent: str,
    level: AlertLevel,
) -> QIcon:
    icon = QIcon()
    for size in _ICON_SIZES:
        icon.addPixmap(render_tray_pixmap(size, value, fraction, accent, level))
    return icon


class TrayController(QObject):
    """Owns one QSystemTrayIcon per pinned provider and a shared context menu."""

    def __init__(
        self,
        *,
        on_toggle_window: Callable[[], None],
        on_refresh: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_toggle_window = on_toggle_window
        self.icons: dict[str, QSystemTrayIcon] = {}

        self.menu = QMenu()
        self.open_action = QAction("열기 / 숨기기", self.menu)
        self.refresh_action = QAction("새로고침", self.menu)
        self.settings_action = QAction("설정", self.menu)
        self.quit_action = QAction("종료", self.menu)
        self.open_action.triggered.connect(on_toggle_window)
        self.refresh_action.triggered.connect(on_refresh)
        self.settings_action.triggered.connect(on_settings)
        self.quit_action.triggered.connect(on_quit)
        self.menu.addAction(self.open_action)
        self.menu.addAction(self.refresh_action)
        self.menu.addAction(self.settings_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    @property
    def active(self) -> bool:
        return bool(self.icons) and self.is_available()

    def set_providers(self, provider_ids: tuple[str, ...], cards: dict[str, ProviderCard]) -> None:
        if tuple(self.icons) == provider_ids:
            return
        # Order matters and Windows cannot reorder live icons, so rebuild.
        for icon in self.icons.values():
            icon.hide()
            icon.deleteLater()
        self.icons = {}

        # Windows places the newest icon closest to the clock, so create them
        # right-to-left to read in the chosen order left-to-right.
        for provider_id in reversed(provider_ids):
            icon = QSystemTrayIcon(self)
            icon.setContextMenu(self.menu)
            icon.activated.connect(self._handle_activated)
            self.icons[provider_id] = icon
            self.update(provider_id, cards[provider_id])
            icon.show()
        self.icons = {provider_id: self.icons[provider_id] for provider_id in provider_ids}

    def update(self, provider_id: str, card: ProviderCard) -> None:
        icon = self.icons.get(provider_id)
        if icon is None:
            return
        icon.setIcon(render_tray_icon(card.compact_value(), card.fraction, card.accent, card.level))
        icon.setToolTip(card.summary_text())

    def hide_all(self) -> None:
        for icon in self.icons.values():
            icon.hide()

    def _handle_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_toggle_window()
