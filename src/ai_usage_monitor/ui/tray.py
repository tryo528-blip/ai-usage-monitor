"""Up to three live readouts in the Windows taskbar notification area.

Each pinned provider gets its own tray icon: a dark tile (readable on light and
dark taskbars) with the two-character code on top in the provider's color and
the remaining percentage below, always two digits. Read left to right, three
icons spell out e.g. C5 90 · CW 95 · FW 99.
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
# size separately keeps the characters sharp instead of letting Windows resample.
_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64)


def _fit_font(size: int, fraction: float) -> QFont:
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(6, round(size * fraction)))
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -size * 0.02)
    return font


def render_tray_pixmap(
    size: int,
    code: str,
    value: str,
    accent: str,
    level: AlertLevel,
) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(0, 0, size, size)
    radius = size * 0.18
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.BACKGROUND))
    painter.drawRoundedRect(rect, radius, radius)

    # Two equal rows: the code (who) above, the number (how much) below. The
    # number row is a touch larger because it is the part that changes.
    half = size / 2
    top = QRectF(0, size * 0.02, size, half)
    bottom = QRectF(0, half - size * 0.04, size, half)
    painter.setFont(_fit_font(size, 0.47))
    painter.setPen(QColor(accent))
    painter.drawText(top, Qt.AlignmentFlag.AlignCenter, code)
    painter.setFont(_fit_font(size, 0.54))
    painter.setPen(QColor(theme.LEVEL_TEXT_COLORS[level]))
    painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, value)
    painter.end()
    return pixmap


def render_tray_icon(code: str, value: str, accent: str, level: AlertLevel) -> QIcon:
    icon = QIcon()
    for size in _ICON_SIZES:
        icon.addPixmap(render_tray_pixmap(size, code, value, accent, level))
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
        icon.setIcon(
            render_tray_icon(card.short_name, card.compact_value(), card.accent, card.level)
        )
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
