from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
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
from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.collectors.grok import GrokCollector
from ai_usage_monitor.collectors.manual import ManualCollector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.providers import (
    PROVIDER_DEFINITION_BY_ID,
    PROVIDER_DEFINITIONS,
    get_visible_provider_ids,
)
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import SecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectorManager
from ai_usage_monitor.services.status_policy import determine_status

from .provider_card import ProviderCard
from .settings_dialog import SettingsDialog

_CARD_WIDTH = 62
_CARD_HEIGHT = 104
_CARD_SPACING = 8
_MARGIN_X = 14
_WINDOW_HEIGHT = 180
_EMPTY_WINDOW_HEIGHT = 60
_REFRESH_WIDTH = 42
_SETTINGS_WIDTH = 42
_MIN_WINDOW_WIDTH = 230
_TITLE_ROW_HEIGHT = 32
_CONTROL_HEIGHT = 32


def _window_width(card_count: int) -> int:
    row = 0
    if card_count > 0:
        row = card_count * _CARD_WIDTH + (card_count - 1) * _CARD_SPACING
    return max(_MIN_WINDOW_WIDTH, row + 2 * _MARGIN_X)


def _window_height(card_count: int) -> int:
    return _WINDOW_HEIGHT if card_count else _EMPTY_WINDOW_HEIGHT


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
        self._set_font_10()
        self._drag_position: QPoint | None = None

        self.secret_store = secret_store or SecretStore()
        self.settings_store = settings_store or SettingsStore()
        self.database = database or UsageDatabase(database_path)
        self.startup_refresh = startup_refresh
        self.selected_provider_ids = get_visible_provider_ids(self.settings_store.load())
        self._uses_default_collector_manager = collector_manager is None

        self._build_ui()
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

        if event.position().y() <= _TITLE_ROW_HEIGHT + 6 and self.childAt(
            event.position().toPoint()
        ) not in (
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

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("app_frame")
        root.setFont(self.font())
        root.setStyleSheet(
            "#app_frame {"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #0b1020, stop:1 #12192d);"
            "border: 1px solid #293857;"
            "border-radius: 20px;"
            "}"
            "QLabel#brand_title { color: #ebf2ff; }"
            "QLabel#local_badge {"
            "color: #73c7ff; background-color: #1f2e4a;"
            "border-radius: 7px; padding: 1px 6px;"
            "}"
            "QPushButton#primary_action {"
            "background-color: #26344f; color: #f2f6ff;"
            "border: 1px solid #334664; border-radius: 9px;"
            "font-weight: bold;"
            "}"
            "QPushButton#primary_action:hover { background-color: #344766; }"
            "QPushButton#window_action {"
            "background-color: #eef1f6; color: #202735;"
            "border: 1px solid #cbd3df; border-radius: 9px;"
            "font-weight: bold;"
            "}"
            "QPushButton#window_action:hover { background-color: #ffffff; }"
            "QPushButton#close_action:hover {"
            "background-color: #ff6b73; color: #ffffff;"
            "border-color: #ff6b73;"
            "}"
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(_MARGIN_X, 14, _MARGIN_X, 14)
        layout.setSpacing(12)

        header = QWidget(root)
        header.setFixedHeight(_TITLE_ROW_HEIGHT)
        title_row = QHBoxLayout(header)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        self.brand_widget = QWidget(header)
        brand_row = QHBoxLayout(self.brand_widget)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(7)
        live_dot = QLabel("●", self.brand_widget)
        live_dot.setStyleSheet("color: #33e8b8;")
        live_dot_font = QFont(self.font())
        live_dot_font.setPointSize(7)
        live_dot.setFont(live_dot_font)
        self.title_label = QLabel("AI USAGE", self.brand_widget)
        self.title_label.setObjectName("brand_title")
        title_font = QFont(self.font())
        title_font.setPointSize(9)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.subtitle_label = QLabel("LOCAL", self.brand_widget)
        self.subtitle_label.setObjectName("local_badge")
        subtitle_font = QFont(self.font())
        subtitle_font.setPointSize(6)
        self.subtitle_label.setFont(subtitle_font)
        brand_row.addWidget(live_dot)
        brand_row.addWidget(self.title_label)
        brand_row.addWidget(self.subtitle_label)

        button_font = QFont(self.font())
        button_font.setPointSize(8)
        self.refresh_button = QPushButton("REF", header)
        self.settings_button = QPushButton("SET", header)
        self.minimize_button = QPushButton("—", header)
        self.close_button = QPushButton("×", header)
        for button in (
            self.refresh_button,
            self.settings_button,
            self.minimize_button,
            self.close_button,
        ):
            button.setFont(button_font)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.refresh_button.setObjectName("primary_action")
        self.settings_button.setObjectName("primary_action")
        self.minimize_button.setObjectName("window_action")
        self.close_button.setObjectName("close_action")
        self.close_button.setStyleSheet(
            "QPushButton {"
            "background-color: #eef1f6; color: #202735;"
            "border: 1px solid #cbd3df; border-radius: 9px;"
            "font-weight: bold;"
            "}"
            "QPushButton:hover {"
            "background-color: #ff6b73; color: #ffffff; border-color: #ff6b73;"
            "}"
        )
        self.refresh_button.setFixedSize(_REFRESH_WIDTH, _CONTROL_HEIGHT)
        self.settings_button.setFixedSize(_SETTINGS_WIDTH, _CONTROL_HEIGHT)
        self.minimize_button.setFixedSize(32, _CONTROL_HEIGHT)
        self.close_button.setFixedSize(32, _CONTROL_HEIGHT)
        self.refresh_button.setToolTip("새로고침")
        self.settings_button.setToolTip("설정")
        self.minimize_button.setToolTip("최소화")
        self.close_button.setToolTip("닫기")

        title_row.addWidget(self.brand_widget)
        title_row.addStretch(1)
        title_row.addWidget(self.refresh_button)
        title_row.addWidget(self.settings_button)
        title_row.addWidget(self.minimize_button)
        title_row.addWidget(self.close_button)
        layout.addWidget(header)

        self.cards_container = QWidget(root)
        self.cards_container.setFixedHeight(108)
        self.rows_layout = QHBoxLayout(self.cards_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(_CARD_SPACING)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards = {
            definition.provider_id: ProviderCard(
                definition.title,
                full_name=definition.full_name or definition.title,
                summary_type=definition.summary_type,
                quota_fields=definition.quota_fields,
                omit_missing_quota=definition.omit_missing_quota,
                balance_display=definition.balance_display,
            )
            for definition in PROVIDER_DEFINITIONS
        }
        for card in self.cards.values():
            card.setFixedSize(_CARD_WIDTH, _CARD_HEIGHT)
        layout.addWidget(self.cards_container)

        self.setCentralWidget(root)
        self._sync_visible_cards()

    def _build_collectors(self, *, collector_manager: CollectorManager | None = None) -> None:
        if collector_manager is None:
            collector_manager = CollectorManager(self._build_default_collectors())
        self.collector_manager = collector_manager
        self.collector_manager.register_callback(self._handle_result)

    def _build_default_collectors(self) -> list[Collector]:
        selected = set(self.selected_provider_ids)
        collectors = []
        if selected & {"codex", "codex_5h"}:
            collectors.append(CodexAppServerCollector())
        if "grok" in selected:
            collectors.append(GrokCollector())
        if "deepseek" in selected:
            collectors.append(DeepSeekCollector(secret_store=self.secret_store))

        for provider_id in ("zai", "kimi3"):
            if provider_id in selected:
                definition = PROVIDER_DEFINITION_BY_ID[provider_id]
                collectors.append(
                    ManualCollector(
                        provider_id,
                        definition.full_name or definition.title,
                        secret_store=self.secret_store,
                        secret_key=f"{provider_id}.api_key",
                    )
                )
        if selected & {"claude", "claude_5h"}:
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

        for provider_id in self.selected_provider_ids:
            card = self.cards[provider_id]
            self.rows_layout.addWidget(card)
            card.show()

        card_count = len(self.selected_provider_ids)
        self.brand_widget.setVisible(card_count >= 5)
        self.cards_container.setVisible(card_count > 0)
        self.setFixedSize(_window_width(card_count), _window_height(card_count))

    def _build_timer(self) -> None:
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(600 * 1000)
        self.refresh_timer.timeout.connect(self.refresh_all)

    def _apply_settings(self) -> bool:
        settings = self.settings_store.load()
        selected_provider_ids = get_visible_provider_ids(settings)
        selection_changed = selected_provider_ids != self.selected_provider_ids
        self.selected_provider_ids = selected_provider_ids
        if selection_changed:
            self._sync_visible_cards()
            if self._uses_default_collector_manager:
                self.collector_manager.collectors = self._build_default_collectors()

        enable_auto = bool(settings.get("auto_refresh", True))
        if enable_auto:
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()
        return selection_changed

    def refresh_all(self) -> None:
        for provider_id in self.selected_provider_ids:
            self.cards[provider_id].set_loading()
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
        cards = [
            card
            for key, card in self.cards.items()
            if key in self.selected_provider_ids
            and (key == result.provider_id or key.startswith(f"{result.provider_id}_"))
        ]
        if not cards:
            return

        snapshot = result.snapshot
        normalized_status = determine_status(snapshot)
        if normalized_status != snapshot.status:
            snapshot = snapshot.model_copy(update={"status": normalized_status})

        for card in cards:
            card.set_snapshot(snapshot)
        try:
            self.database.save_snapshot(snapshot)
        except Exception:
            for card in cards:
                card.set_error("SQLite 저장 실패")

    def _set_font_10(self) -> None:
        font = QFont(self.font())
        font.setFamily("Noto Sans KR")
        font.setPointSize(10)
        self.setFont(font)
