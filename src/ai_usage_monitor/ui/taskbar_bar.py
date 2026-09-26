"""A slim readout that sits on the Windows taskbar.

Windows 11 has no API for adding text to the taskbar, so this is a small
frameless, always-on-top tool window placed inside the taskbar strip. It shows
up to three providers in one line, e.g. ``C5 90  CW 95  FW 99``: the code in the
provider's color, the remaining percentage (always two digits) in white or the
warning color. Drag it sideways to move it; the position is remembered.

Clicking the taskbar raises the taskbar above every other window, so on
Windows the bar re-asserts "topmost" twice a second. It hides itself while a
full-screen app (game, video) is in front.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter
from PySide6.QtWidgets import QMenu, QWidget

from . import theme
from .fonts import ensure_pretendard_font
from .theme import AlertLevel

if TYPE_CHECKING:
    from .provider_card import ProviderCard

_IS_WINDOWS = sys.platform == "win32"
_KEEP_ON_TOP_INTERVAL_MS = 500
_PADDING_X = 12
_ITEM_GAP = 14
_CODE_GAP = 4
_PILL_HEIGHT_RATIO = 0.7
# Default spot: just right of the Windows 11 weather widget on the left.
DEFAULT_OFFSET_X = 140


def taskbar_rect(screen_geometry: QRect, available: QRect) -> QRect:
    """The strip the taskbar reserves, or a 48px bottom strip when it auto-hides."""

    if available.bottom() < screen_geometry.bottom():
        return QRect(
            screen_geometry.left(),
            available.bottom() + 1,
            screen_geometry.width(),
            screen_geometry.bottom() - available.bottom(),
        )
    if available.top() > screen_geometry.top():
        return QRect(
            screen_geometry.left(),
            screen_geometry.top(),
            screen_geometry.width(),
            available.top() - screen_geometry.top(),
        )
    return QRect(screen_geometry.left(), screen_geometry.bottom() - 47, screen_geometry.width(), 48)


class _Item:
    __slots__ = ("code", "value", "accent", "level", "tooltip")

    def __init__(self, code: str, value: str, accent: str, level: AlertLevel, tooltip: str):
        self.code = code
        self.value = value
        self.accent = accent
        self.level = level
        self.tooltip = tooltip


class TaskbarBar(QWidget):
    clicked = Signal()
    moved = Signal(int)

    def __init__(
        self,
        *,
        on_toggle_window: Callable[[], None],
        on_refresh: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        offset_x: int = DEFAULT_OFFSET_X,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(None)
        if parent is not None:
            # Lifetime only; the bar stays a top-level window.
            parent.destroyed.connect(self.deleteLater)
        self.setWindowTitle("AI Usage Taskbar")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.items: dict[str, _Item] = {}
        self.offset_x = offset_x
        self._press_pos: QPoint | None = None
        self._dragged = False
        self.clicked.connect(on_toggle_window)

        self.menu = QMenu()
        self.menu.addAction("열기 / 숨기기", on_toggle_window)
        self.menu.addAction("새로고침", on_refresh)
        self.menu.addAction("설정", on_settings)
        self.menu.addSeparator()
        self.menu.addAction("종료", on_quit)

        self._code_font = QFont(ensure_pretendard_font())
        self._code_font.setBold(True)
        self._value_font = QFont(self._code_font)

        self._keep_on_top = QTimer(self)
        self._keep_on_top.setInterval(_KEEP_ON_TOP_INTERVAL_MS)
        self._keep_on_top.timeout.connect(self._reassert)

    # -- state ---------------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self.items)

    def set_providers(self, provider_ids: tuple[str, ...], cards: dict[str, ProviderCard]) -> None:
        self.items = {}
        for provider_id in provider_ids:
            self.items[provider_id] = _Item("", "--", theme.DEFAULT_ACCENT, AlertLevel.MUTED, "")
            self.update_card(provider_id, cards[provider_id])
        if self.items:
            self.place()
            self.show()
            self._keep_on_top.start()
        else:
            self.hide_all()

    def update_card(self, provider_id: str, card: ProviderCard) -> None:
        item = self.items.get(provider_id)
        if item is None:
            return
        item.code = card.short_name
        item.value = card.compact_value()
        item.accent = card.accent
        item.level = card.level
        item.tooltip = card.summary_text()
        self.setToolTip("\n".join(entry.tooltip for entry in self.items.values()))
        if self.isVisible():
            self.place()
        self.update()

    def hide_all(self) -> None:
        self._keep_on_top.stop()
        self.hide()

    def text(self) -> str:
        return "  ".join(f"{item.code} {item.value}" for item in self.items.values())

    # -- geometry ------------------------------------------------------------

    def _strip(self) -> QRect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return taskbar_rect(screen.geometry(), screen.availableGeometry())

    def _fonts_for(self, height: int) -> None:
        self._code_font.setPixelSize(max(11, round(height * 0.38)))
        self._value_font.setPixelSize(max(13, round(height * 0.50)))

    def _content_width(self) -> float:
        code_metrics = QFontMetricsF(self._code_font)
        value_metrics = QFontMetricsF(self._value_font)
        width = 2 * _PADDING_X
        for index, item in enumerate(self.items.values()):
            if index:
                width += _ITEM_GAP
            width += code_metrics.horizontalAdvance(item.code) + _CODE_GAP
            width += value_metrics.horizontalAdvance("00")
        return width

    def place(self) -> None:
        strip = self._strip()
        height = max(24, round(strip.height() * _PILL_HEIGHT_RATIO))
        self._fonts_for(height)
        width = round(self._content_width())
        max_offset = max(0, strip.width() - width)
        self.offset_x = max(0, min(self.offset_x, max_offset))
        top = strip.top() + (strip.height() - height) // 2
        self.setGeometry(strip.left() + self.offset_x, top, width, height)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2
        painter.setPen(QColor(theme.BORDER))
        painter.setBrush(QColor(theme.BACKGROUND))
        painter.drawRoundedRect(rect, radius, radius)

        code_metrics = QFontMetricsF(self._code_font)
        value_metrics = QFontMetricsF(self._value_font)
        baseline = rect.center().y() + value_metrics.capHeight() / 2
        x = float(_PADDING_X)
        for index, item in enumerate(self.items.values()):
            if index:
                x += _ITEM_GAP
            painter.setFont(self._code_font)
            painter.setPen(QColor(item.accent))
            painter.drawText(QPoint(round(x), round(baseline)), item.code)
            x += code_metrics.horizontalAdvance(item.code) + _CODE_GAP
            painter.setFont(self._value_font)
            painter.setPen(QColor(theme.LEVEL_TEXT_COLORS[item.level]))
            # Right-align in a fixed two-digit box so the layout never jitters.
            slot = value_metrics.horizontalAdvance("00")
            advance = value_metrics.horizontalAdvance(item.value)
            painter.drawText(QPoint(round(x + slot - advance), round(baseline)), item.value)
            x += slot
        painter.end()

    # -- interaction ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_offset = self.offset_x
            self._dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None:
            return
        dx = event.globalPosition().toPoint().x() - self._press_pos.x()
        if abs(dx) > 3:
            self._dragged = True
        if self._dragged:
            self.offset_x = self._press_offset + dx
            self.place()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return super().mouseReleaseEvent(event)
        self._press_pos = None
        if self._dragged:
            self.moved.emit(self.offset_x)
        else:
            self.clicked.emit()

    def contextMenuEvent(self, event) -> None:
        self.menu.popup(event.globalPos())

    # -- staying visible on Windows --------------------------------------------

    def _reassert(self) -> None:
        if not _IS_WINDOWS or not self.items:
            return
        try:
            if _foreground_is_fullscreen(self.screen().geometry()):
                if self.isVisible():
                    self.hide()
                return
            if not self.isVisible():
                self.show()
            _set_topmost(int(self.winId()))
        except Exception:  # noqa: BLE001 - a Win32 hiccup must never crash the app
            pass


def _set_topmost(hwnd: int) -> None:
    import ctypes

    hwnd_topmost = -1
    flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    ctypes.windll.user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, flags)


def _foreground_is_fullscreen(screen: QRect) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, 64)
    if name.value in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    # Window rects are in physical pixels; compare against the scaled screen.
    ratio = QGuiApplication.primaryScreen().devicePixelRatio()
    return (
        rect.left <= screen.left() * ratio
        and rect.top <= screen.top() * ratio
        and rect.right >= (screen.right() + 1) * ratio
        and rect.bottom >= (screen.bottom() + 1) * ratio
    )
