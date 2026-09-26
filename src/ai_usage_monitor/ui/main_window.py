from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ai_usage_monitor.collectors.antyg_bridge import AntigravityCollector
from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.collectors.claude_bridge import ClaudeBridgeCollector
from ai_usage_monitor.collectors.codex_app_server import CodexAppServerCollector
from ai_usage_monitor.collectors.grok import GrokCollector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.providers import (
    PROVIDER_DEFINITION_BY_ID,
    PROVIDER_DEFINITIONS,
    TASKBAR_MODE_SETTING,
    TASKBAR_OFFSET_SETTING,
    get_taskbar_provider_ids,
    get_visible_provider_ids,
)
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import SecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectorManager
from ai_usage_monitor.services.status_policy import determine_status

from . import theme
from .fonts import pretendard_regular
from .provider_card import CARD_HEIGHT, CARD_WIDTH, ProviderCard
from .settings_dialog import SettingsDialog
from .taskbar_bar import DEFAULT_OFFSET_X, MODE_EMBED, TaskbarBar

# Cards of one provider (5H and WEEK) sit closer together than cards of
# different providers, so the row reads as groups rather than a flat list.
_PAIR_SPACING = 5
_GROUP_SPACING = 12
_MARGIN_X = 14
_MARGIN_TOP = 12
_MARGIN_BOTTOM = 14
_SECTION_SPACING = 10
_MIN_WINDOW_WIDTH = 240
_TITLE_ROW_HEIGHT = 28
_CONTROL_SIZE = 28

_WINDOW_STYLE = f"""
#app_frame {{
    background-color: {theme.BACKGROUND};
    border: 1px solid {theme.BORDER};
    border-radius: 18px;
}}
QLabel {{ background: transparent; }}
QLabel#brand_title {{ color: {theme.TEXT}; }}
QLabel#updated_label {{ color: {theme.TEXT_FAINT}; }}
QPushButton#icon_action {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
}}
QPushButton#icon_action:hover {{ background-color: {theme.SURFACE_HOVER}; }}
QPushButton#icon_action:pressed {{ background-color: {theme.BORDER}; }}
QPushButton#close_action {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
}}
QPushButton#close_action:hover {{ background-color: #e5484d; }}
"""


def _group_of(provider_id: str) -> str:
    definition = PROVIDER_DEFINITION_BY_ID[provider_id]
    return definition.collector_id or provider_id


def _row_width(provider_ids: tuple[str, ...]) -> int:
    if not provider_ids:
        return 0
    width = len(provider_ids) * CARD_WIDTH
    for previous, current in zip(provider_ids, provider_ids[1:], strict=False):
        same_group = _group_of(previous) == _group_of(current)
        width += _PAIR_SPACING if same_group else _GROUP_SPACING
    return width


def _window_width(provider_ids: tuple[str, ...]) -> int:
    return max(_MIN_WINDOW_WIDTH, _row_width(provider_ids) + 2 * _MARGIN_X)


def _window_height(card_count: int) -> int:
    height = _MARGIN_TOP + _TITLE_ROW_HEIGHT + _MARGIN_BOTTOM
    if card_count:
        height += _SECTION_SPACING + CARD_HEIGHT
    return height


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        secret_store: SecretStore | None = None,
        settings_store: SettingsStore | None = None,
        database: UsageDatabase | None = None,
        collector_manager: CollectorManager | None = None,
        startup_refresh: bool = True,
        database_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("AI Usage Monitor")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(pretendard_regular(10))
        self._drag_position: QPoint | None = None
        self._quitting = False

        self.secret_store = secret_store or SecretStore()
        self.settings_store = settings_store or SettingsStore()
        self.database = database or UsageDatabase(database_path)
        self.startup_refresh = startup_refresh
        settings = self.settings_store.load()
        self.selected_provider_ids = get_visible_provider_ids(settings)
        self.taskbar_provider_ids = get_taskbar_provider_ids(settings)
        self._uses_default_collector_manager = collector_manager is None

        self._build_ui()
        self._build_taskbar_bar()
        self._build_collectors(collector_manager=collector_manager)
        self._build_timer()
        self._apply_settings()

        self.refresh_button.clicked.connect(self.refresh_all)
        self.settings_button.clicked.connect(self._open_settings)
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button.clicked.connect(self.close)
        if self.startup_refresh:
            QTimer.singleShot(0, self.refresh_all)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        if event.position().y() <= _MARGIN_TOP + _TITLE_ROW_HEIGHT + 4 and self.childAt(
            event.position().toPoint()
        ) not in (
            self.refresh_button,
            self.settings_button,
            self.minimize_button,
            self.close_button,
        ):
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        # With the taskbar readout showing, the close button tucks the window
        # away and the readout's right-click "종료" really quits.
        if not self._quitting and self.taskbar_bar.active:
            event.ignore()
            self.hide()
            return
        self.taskbar_bar.hide_all()
        super().closeEvent(event)
        app = QApplication.instance()
        # App disables quit-on-last-window so hiding the window keeps it alive;
        # an accepted close must then end the event loop explicitly.
        if app is not None and not app.quitOnLastWindowClosed():
            app.quit()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def allow_close(self, *_args) -> None:
        """Let the next close really close, e.g. when Windows logs off."""

        self._quitting = True

    def toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("app_frame")
        root.setFont(self.font())
        root.setStyleSheet(_WINDOW_STYLE)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(_MARGIN_X, _MARGIN_TOP, _MARGIN_X, _MARGIN_BOTTOM)
        layout.setSpacing(_SECTION_SPACING)

        header = QWidget(root)
        header.setFixedHeight(_TITLE_ROW_HEIGHT)
        title_row = QHBoxLayout(header)
        title_row.setContentsMargins(2, 0, 0, 0)
        title_row.setSpacing(2)

        self.brand_widget = QWidget(header)
        brand_row = QHBoxLayout(self.brand_widget)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(7)
        self.title_label = QLabel("AI Usage", self.brand_widget)
        self.title_label.setObjectName("brand_title")
        self.title_label.setFont(theme.bold_font(self.font(), 10))
        self.updated_label = QLabel("", self.brand_widget)
        self.updated_label.setObjectName("updated_label")
        updated_font = QFont(self.font())
        updated_font.setPointSize(8)
        self.updated_label.setFont(updated_font)
        # Reserve the widest text up front so the header never reflows when
        # the first timestamp arrives.
        self.title_label.setFixedWidth(self.title_label.sizeHint().width() + 2)
        self.updated_label.setFixedWidth(
            self.updated_label.fontMetrics().horizontalAdvance("00:00 갱신") + 4
        )
        brand_row.addWidget(self.title_label)
        brand_row.addWidget(self.updated_label)

        self.refresh_button = QPushButton(header)
        self.settings_button = QPushButton(header)
        self.minimize_button = QPushButton(header)
        self.close_button = QPushButton(header)
        for button, icon, name, tip in (
            (self.refresh_button, theme.refresh_icon(), "icon_action", "새로고침"),
            (self.settings_button, theme.settings_icon(), "icon_action", "설정"),
            (self.minimize_button, theme.minimize_icon(), "icon_action", "최소화"),
            (self.close_button, theme.close_icon(), "close_action", "닫기"),
        ):
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
            button.setObjectName(name)
            button.setToolTip(tip)
            button.setFixedSize(_CONTROL_SIZE, _CONTROL_SIZE)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        title_row.addWidget(self.brand_widget)
        title_row.addStretch(1)
        title_row.addWidget(self.refresh_button)
        title_row.addWidget(self.settings_button)
        title_row.addSpacing(6)
        title_row.addWidget(self.minimize_button)
        title_row.addWidget(self.close_button)
        layout.addWidget(header)

        self.cards_container = QWidget(root)
        self.cards_container.setFixedHeight(CARD_HEIGHT)
        self.rows_layout = QHBoxLayout(self.cards_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards = {
            definition.provider_id: ProviderCard(
                definition.title,
                full_name=definition.full_name or definition.title,
                summary_type=definition.summary_type,
                quota_fields=definition.quota_fields,
                omit_missing_quota=definition.omit_missing_quota,
                balance_display=definition.balance_display,
                accent=theme.accent_for(definition.provider_id),
            )
            for definition in PROVIDER_DEFINITIONS
        }
        layout.addWidget(self.cards_container)
        layout.addStretch(1)

        self.setCentralWidget(root)
        self._sync_visible_cards()

    def _build_taskbar_bar(self) -> None:
        settings = self.settings_store.load()
        offset = settings.get(TASKBAR_OFFSET_SETTING, DEFAULT_OFFSET_X)
        self.taskbar_bar = TaskbarBar(
            on_toggle_window=self.toggle_visible,
            on_refresh=self.refresh_all,
            on_settings=self._open_settings,
            on_quit=self.quit_app,
            offset_x=offset if isinstance(offset, int) else DEFAULT_OFFSET_X,
            mode=str(settings.get(TASKBAR_MODE_SETTING, MODE_EMBED)),
            parent=self,
        )
        self.taskbar_bar.moved.connect(self._save_taskbar_offset)
        self.taskbar_bar.mode_changed.connect(self._save_taskbar_mode)
        self.taskbar_bar.set_providers(self.taskbar_provider_ids, self.cards)

    def _save_taskbar_offset(self, offset: int) -> None:
        settings = self.settings_store.load()
        settings[TASKBAR_OFFSET_SETTING] = offset
        self.settings_store.save(settings)

    def _save_taskbar_mode(self, mode: str) -> None:
        settings = self.settings_store.load()
        settings[TASKBAR_MODE_SETTING] = mode
        self.settings_store.save(settings)

    def _build_collectors(self, *, collector_manager: CollectorManager | None = None) -> None:
        if collector_manager is None:
            collector_manager = CollectorManager(self._build_default_collectors())
        self.collector_manager = collector_manager
        self.collector_manager.register_callback(self._handle_result)

    @property
    def tracked_provider_ids(self) -> tuple[str, ...]:
        """Cards fed by collectors: the visible row plus the taskbar readout."""

        tracked = set(self.selected_provider_ids) | set(self.taskbar_provider_ids)
        return tuple(
            definition.provider_id
            for definition in PROVIDER_DEFINITIONS
            if definition.provider_id in tracked
        )

    def _build_default_collectors(self) -> list[Collector]:
        selected = set(self.tracked_provider_ids)
        collectors = []
        if selected & {"codex", "codex_5h"}:
            collectors.append(CodexAppServerCollector())
        if "grok" in selected:
            collectors.append(GrokCollector())
        if selected & {"claude", "claude_5h", "claude_fable"}:
            collectors.append(ClaudeBridgeCollector())
        if selected & {"antyg", "antyg_5h"}:
            collectors.append(AntigravityCollector())
        if "openrouter" in selected:
            collectors.append(OpenRouterCollector(secret_store=self.secret_store))
        return collectors

    def _sync_visible_cards(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            card = item.widget()
            if card is not None:
                card.setParent(None)
                card.hide()

        previous: str | None = None
        for provider_id in self.selected_provider_ids:
            if previous is not None:
                same_group = _group_of(previous) == _group_of(provider_id)
                self.rows_layout.addSpacing(_PAIR_SPACING if same_group else _GROUP_SPACING)
            card = self.cards[provider_id]
            self.rows_layout.addWidget(card)
            card.show()
            previous = provider_id

        card_count = len(self.selected_provider_ids)
        self.cards_container.setVisible(card_count > 0)
        self.setFixedSize(
            _window_width(self.selected_provider_ids),
            _window_height(card_count),
        )

    def _build_timer(self) -> None:
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(600 * 1000)
        self.refresh_timer.timeout.connect(self.refresh_all)

    def _apply_settings(self) -> bool:
        settings = self.settings_store.load()
        selected_provider_ids = get_visible_provider_ids(settings)
        taskbar_provider_ids = get_taskbar_provider_ids(settings)
        selection_changed = selected_provider_ids != self.selected_provider_ids
        taskbar_changed = taskbar_provider_ids != self.taskbar_provider_ids
        self.selected_provider_ids = selected_provider_ids
        self.taskbar_provider_ids = taskbar_provider_ids
        if selection_changed:
            self._sync_visible_cards()
        if taskbar_changed:
            self.taskbar_bar.set_providers(self.taskbar_provider_ids, self.cards)
        if (selection_changed or taskbar_changed) and self._uses_default_collector_manager:
            self.collector_manager.collectors = self._build_default_collectors()

        enable_auto = bool(settings.get("auto_refresh", True))
        if enable_auto:
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()
        return selection_changed or taskbar_changed

    def refresh_all(self) -> None:
        for provider_id in self.tracked_provider_ids:
            self.cards[provider_id].set_loading()
            self.taskbar_bar.update_card(provider_id, self.cards[provider_id])
        self.collector_manager.refresh()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            secret_store=self.secret_store,
            settings_store=self.settings_store,
            show_claude_auth=True,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selection_changed = self._apply_settings()
            if selection_changed:
                self.refresh_all()

    def _handle_result(self, result) -> None:
        tracked = self.tracked_provider_ids
        provider_ids = [
            key
            for key in self.cards
            if key in tracked
            and (key == result.provider_id or key.startswith(f"{result.provider_id}_"))
        ]
        if not provider_ids:
            return

        snapshot = result.snapshot
        normalized_status = determine_status(snapshot)
        if normalized_status != snapshot.status:
            snapshot = snapshot.model_copy(update={"status": normalized_status})

        for provider_id in provider_ids:
            self.cards[provider_id].set_snapshot(snapshot)
            self.taskbar_bar.update_card(provider_id, self.cards[provider_id])
        self.updated_label.setText(f"{datetime.now():%H:%M} 갱신")
        try:
            self.database.save_snapshot(snapshot)
        except Exception:
            for provider_id in provider_ids:
                self.cards[provider_id].set_error("SQLite 저장 실패")
                self.taskbar_bar.update_card(provider_id, self.cards[provider_id])
