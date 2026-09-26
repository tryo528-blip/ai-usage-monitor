"""A slim readout that sits on the Windows taskbar.

It shows up to three providers in one line, e.g. ``C5 90  CW 95  FW 99``: the
code in the provider's color, the remaining percentage (always two digits) in
white or the warning color. Drag it sideways to move it; the position is
remembered.

Windows 11 has no API for adding text to the taskbar, so there are two modes,
switchable from the right-click menu:

* ``embed`` (default on Windows): the bar becomes a child window of the taskbar
  itself (``Shell_TrayWnd``), the approach TrafficMonitor uses. It then moves,
  hides and stacks with the taskbar. If Explorer restarts, it re-attaches.
* ``overlay``: a frameless always-on-top tool window placed over the taskbar
  that re-asserts "topmost" twice a second and hides for full-screen apps. The
  Windows 11 taskbar can still cover it while another app is active.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QWindow
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
MODE_EMBED = "embed"
MODE_OVERLAY = "overlay"
_MODE_LABELS = {MODE_EMBED: "작업 표시줄에 붙이기", MODE_OVERLAY: "작업 표시줄 위에 띄우기"}


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
    mode_changed = Signal(str)

    def __init__(
        self,
        *,
        on_toggle_window: Callable[[], None],
        on_refresh: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        offset_x: int = DEFAULT_OFFSET_X,
        mode: str = MODE_EMBED,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(None)
        if parent is not None:
            # Lifetime only; the bar stays a top-level window.
            parent.destroyed.connect(self.deleteLater)
        self.setWindowTitle("AI Usage Taskbar")
        self.setWindowFlags(_OVERLAY_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.items: dict[str, _Item] = {}
        self.offset_x = offset_x
        self.mode = mode if mode in _MODE_LABELS else MODE_EMBED
        self._host: QWindow | None = None
        self._host_hwnd = 0
        self._backdrop = QColor("#f0f0f0")
        self._press_pos: QPoint | None = None
        self._dragged = False
        self.clicked.connect(on_toggle_window)

        self.menu = QMenu()
        self.menu.addAction("열기 / 숨기기", on_toggle_window)
        self.menu.addAction("새로고침", on_refresh)
        self.menu.addAction("설정", on_settings)
        self.mode_action = self.menu.addAction("", self._toggle_mode)
        self._update_mode_action()
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
            self._apply_mode()
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

    @property
    def embedded(self) -> bool:
        return self._host is not None

    def set_mode(self, mode: str) -> None:
        if mode not in _MODE_LABELS or mode == self.mode:
            return
        self.mode = mode
        self._update_mode_action()
        if self.items:
            self._apply_mode()

    def _toggle_mode(self) -> None:
        self.set_mode(MODE_OVERLAY if self.mode == MODE_EMBED else MODE_EMBED)
        self.mode_changed.emit(self.mode)

    def _update_mode_action(self) -> None:
        other = MODE_OVERLAY if self.mode == MODE_EMBED else MODE_EMBED
        self.mode_action.setText(f"표시 방식 바꾸기 → {_MODE_LABELS[other]}")

    def _apply_mode(self) -> None:
        self.hide()
        taskbar = _find_taskbar() if self.mode == MODE_EMBED and _IS_WINDOWS else 0
        if taskbar:
            self.setWindowFlags(_EMBED_FLAGS)
            self.winId()  # create the native window before re-parenting it
            self._host = QWindow.fromWinId(taskbar)
            self._host_hwnd = taskbar
            self.windowHandle().setParent(self._host)
            self._backdrop = QColor(_taskbar_backdrop())
        else:
            if self._host is not None and self.windowHandle() is not None:
                self.windowHandle().setParent(None)
            self._host = None
            self._host_hwnd = 0
            self.setWindowFlags(_OVERLAY_FLAGS)
        self.place()
        self.show()

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
        top = (strip.height() - height) // 2
        if self.embedded:
            # Child of the taskbar: coordinates are relative to it.
            self.setGeometry(self.offset_x, top, width, height)
        else:
            self.setGeometry(strip.left() + self.offset_x, strip.top() + top, width, height)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if self.embedded:
            # A child window cannot be see-through, so fill the corners around
            # the pill with the taskbar's own color.
            painter.fillRect(self.rect(), self._backdrop)
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
            if self.mode == MODE_EMBED:
                taskbar = _find_taskbar()
                if taskbar != self._host_hwnd:
                    # Explorer restarted (new taskbar) or embedding had failed.
                    self._apply_mode()
                    return
                if self.embedded:
                    _raise_child(int(self.winId()))
                    return
            if _foreground_is_fullscreen(self.screen().geometry()):
                if self.isVisible():
                    self.hide()
                return
            if not self.isVisible():
                self.show()
            _set_topmost(int(self.winId()))
        except Exception:  # noqa: BLE001 - a Win32 hiccup must never crash the app
            pass


_OVERLAY_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)
_EMBED_FLAGS = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus
_SWP_KEEP = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE


def _find_taskbar() -> int:
    if not _IS_WINDOWS:
        return 0
    import ctypes

    return int(ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None) or 0)


def _raise_child(hwnd: int) -> None:
    import ctypes

    hwnd_top = 0
    ctypes.windll.user32.SetWindowPos(hwnd, hwnd_top, 0, 0, 0, 0, _SWP_KEEP)


def _taskbar_backdrop() -> str:
    """Approximate Windows 11 taskbar color for the current light/dark theme."""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            light, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
    except OSError:
        light = 0
    return "#eeeeee" if light else "#1c1c1c"


def _set_topmost(hwnd: int) -> None:
    import ctypes

    hwnd_topmost = -1
    ctypes.windll.user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, _SWP_KEEP)


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
