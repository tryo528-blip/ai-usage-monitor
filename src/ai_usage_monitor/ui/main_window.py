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

_CARD_WIDTH = 44
_CARD_HEIGHT = 128
_CARD_SPACING = 4
_MARGIN_X = 12
_WINDOW_HEIGHT = 200
_REFRESH_WIDTH = 62
_MIN_WINDOW_WIDTH = 180
_SIDE_EXTRA = 2
_TITLE_ROW_HEIGHT = 34
_CONTROL_HEIGHT = 22


def _window_width(card_count: int) -> int:
    row = 0
    if card_count > 0:
        row = card_count * _CARD_WIDTH + (card_count - 1) * _CARD_SPACING
    return max(_MIN_WINDOW_WIDTH, row + 2 * _MARGIN_X + 2 * _SIDE_EXTRA)


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
            "#app_frame { background-color: #f6f8fc; border: 1px solid #d1d7e2; "
            "border-radius: 12px; }"
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(_MARGIN_X, 8, _MARGIN_X, 4)
        layout.setSpacing(5)

        header = QWidget(root)
        header.setFixedHeight(_TITLE_ROW_HEIGHT)
        title_row = QHBoxLayout(header)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(0)
        self.title_label = QLabel("남은 사용량")
        self.title_label.setFixedHeight(17)
        title_font = QFont(self.font())
        title_font.setPointSize(10)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label = QLabel("AI Usage Monitor")
        self.subtitle_label.setFixedHeight(12)
        subtitle_font = QFont(self.font())
        subtitle_font.setPointSize(7)
        self.subtitle_label.setFont(subtitle_font)
        self.subtitle_label.setStyleSheet("color: #6b7280;")
        title_stack.addWidget(self.title_label)
        title_stack.addWidget(self.subtitle_label)

        self.minimize_button = QPushButton("—")
        self.close_button = QPushButton("×")
        button_font = QFont(self.font())
        button_font.setPointSize(8)
        self.minimize_button.setFont(button_font)
        self.close_button.setFont(button_font)
        self.minimize_button.setFixedSize(20, _CONTROL_HEIGHT)
        self.close_button.setFixedSize(20, _CONTROL_HEIGHT)
        self.minimize_button.setToolTip("최소화")
        self.close_button.setToolTip("닫기")
        self.minimize_button.setFlat(True)
        self.close_button.setFlat(True)
        self.close_button.setStyleSheet("QPushButton { color: #c62828; font-weight: bold; }")
        self.refresh_button = QPushButton("새로고침")
        self.settings_button = QPushButton("설정")
        self.refresh_button.setFont(button_font)
        self.settings_button.setFont(button_font)
        self.refresh_button.setFixedSize(_REFRESH_WIDTH, _CONTROL_HEIGHT)
        self.settings_button.setFixedSize(38, _CONTROL_HEIGHT)
        self.refresh_button.setToolTip("새로고침")
        self.settings_button.setToolTip("설정")
        self.refresh_button.setStyleSheet(
            "QPushButton { background: #ffffff; border: 1px solid #d6deeb; "
            "border-radius: 7px; padding: 0 4px; color: #2b3748; }"
        )
        self.settings_button.setStyleSheet(
            "QPushButton { background: #e6edff; border: 1px solid #d6deeb; "
            "border-radius: 7px; padding: 0 4px; color: #1f4eb5; font-weight: bold; }"
        )

        title_row.addLayout(title_stack)
        title_row.addStretch(1)
        title_row.addWidget(self.refresh_button)
        title_row.addWidget(self.settings_button)
        title_row.addWidget(self.minimize_button)
        title_row.addWidget(self.close_button)
        layout.addWidget(header)

        self.rows_layout = QHBoxLayout()
        self.rows_layout.setSpacing(_CARD_SPACING)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards = {
            definition.provider_id: ProviderCard(
                definition.title,
                full_name=definition.full_name or definition.title,
                summary_type=definition.summary_type,
                quota_fields=definition.quota_fields,
                omit_missing_quota=definition.omit_missing_quota,
            )
            for definition in PROVIDER_DEFINITIONS
        }
        for card in self.cards.values():
            card.setFixedSize(_CARD_WIDTH, _CARD_HEIGHT)
        layout.addLayout(self.rows_layout)

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
        if "codex" in selected:
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
                    )
                )
        if selected & {"claude", "claude_5h"}:
            collectors.append(ClaudeBridgeCollector())
        if "antyg" in selected:
            collectors.append(AntigravityCollector())
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

        self.setFixedSize(_window_width(len(self.selected_provider_ids)), _WINDOW_HEIGHT)

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
        font.setPointSize(10)
        self.setFont(font)
