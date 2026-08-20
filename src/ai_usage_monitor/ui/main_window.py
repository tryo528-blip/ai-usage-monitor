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

from ai_usage_monitor.collectors.claude_bridge import ClaudeBridgeCollector
from ai_usage_monitor.collectors.codex_app_server import CodexAppServerCollector
from ai_usage_monitor.collectors.deepseek import DeepSeekCollector
from ai_usage_monitor.collectors.grok import GrokCollector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import SecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectorManager
from ai_usage_monitor.services.status_policy import determine_status

from .provider_card import ProviderCard
from .settings_dialog import SettingsDialog

# Claude collector and card code stay in the repo. Flip this to show Claude again.
SHOW_CLAUDE_IN_UI = False

_CARD_WIDTH = 38
_CARD_HEIGHT = 148
_CARD_SPACING = 6
_MARGIN_X = 6
_WINDOW_HEIGHT = 206
_REFRESH_WIDTH = 66
_SIDE_EXTRA = 6
_TITLE_ROW_HEIGHT = 22


def _is_claude_card(key: str) -> bool:
    return key == "claude" or key.startswith("claude_")


def _window_width(card_count: int) -> int:
    if card_count <= 0:
        return 2 * _MARGIN_X + 2 * _SIDE_EXTRA
    row = card_count * _CARD_WIDTH + (card_count - 1) * _CARD_SPACING
    return row + 2 * _MARGIN_X + 2 * _SIDE_EXTRA


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
        root.setStyleSheet("#app_frame { background-color: #ffffff; border: 1px solid #000000; }")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(_MARGIN_X, 3, _MARGIN_X, 4)
        layout.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(2)
        self.title_label = QLabel("남은 사용량")
        title_font = QFont(self.font())
        title_font.setPointSize(8)
        self.title_label.setFont(title_font)
        self.minimize_button = QPushButton("—")
        self.close_button = QPushButton("×")
        button_font = QFont(self.font())
        button_font.setPointSize(8)
        self.minimize_button.setFont(button_font)
        self.close_button.setFont(button_font)
        self.minimize_button.setFixedSize(20, _TITLE_ROW_HEIGHT)
        self.close_button.setFixedSize(20, _TITLE_ROW_HEIGHT)
        self.minimize_button.setToolTip("최소화")
        self.close_button.setToolTip("닫기")
        self.minimize_button.setFlat(True)
        self.close_button.setFlat(True)
        self.close_button.setStyleSheet("QPushButton { color: #c62828; font-weight: bold; }")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        title_row.addWidget(self.minimize_button)
        title_row.addWidget(self.close_button)
        layout.addLayout(title_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(4)
        self.refresh_button = QPushButton("새로고침")
        self.settings_button = QPushButton("설정")
        self.refresh_button.setFont(button_font)
        self.settings_button.setFont(button_font)
        self.refresh_button.setFixedSize(_REFRESH_WIDTH, _TITLE_ROW_HEIGHT)
        self.settings_button.setFixedSize(40, _TITLE_ROW_HEIGHT)
        self.refresh_button.setToolTip("새로고침")
        self.settings_button.setToolTip("설정")
        action_row.addWidget(self.refresh_button)
        action_row.addWidget(self.settings_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        rows_layout = QHBoxLayout()
        rows_layout.setSpacing(_CARD_SPACING)
        rows_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards = {
            "claude": ProviderCard(
                "클로드",
                summary_type="quota",
                quota_fields=(("weekly", "주간 사용량"),),
                bar_color="#7e57c2",
                bar_light_color="#d1c4e9",
            ),
            "claude_5h": ProviderCard(
                "클로드",
                summary_type="quota",
                quota_fields=(("five_hour", "5시간 사용량"),),
                bar_color="#7e57c2",
                bar_light_color="#d1c4e9",
            ),
            "codex": ProviderCard(
                "코덱스",
                summary_type="quota",
                quota_fields=(("weekly", "주간 사용량"),),
                bar_color="#2e7d32",
                bar_light_color="#c8e6c9",
            ),
            "grok": ProviderCard(
                "그록",
                summary_type="quota",
                quota_fields=(("weekly", "주간 사용량"),),
                bar_color="#ef6c00",
                bar_light_color="#ffe0b2",
            ),
            "openrouter": ProviderCard(
                "오픈라우터",
                summary_type="balance",
                bar_color="#00897b",
                bar_light_color="#b2dfdb",
            ),
            "deepseek": ProviderCard(
                "딥시크",
                summary_type="balance",
                bar_color="#1565c0",
                bar_light_color="#bbdefb",
            ),
        }
        self.cards["claude"].title_label.setText("CLD-W")
        self.cards["claude_5h"].title_label.setText("CLD-5")
        self.cards["codex"].title_label.setText("CDX")
        self.cards["grok"].title_label.setText("Grok")
        self.cards["openrouter"].title_label.setText("O.R")
        self.cards["deepseek"].title_label.setText("DSeek")
        visible_count = 0
        for key, card in self.cards.items():
            card.setFixedSize(_CARD_WIDTH, _CARD_HEIGHT)
            if SHOW_CLAUDE_IN_UI or not _is_claude_card(key):
                rows_layout.addWidget(card)
                visible_count += 1
        layout.addLayout(rows_layout)

        self.setCentralWidget(root)
        self.setFixedSize(_window_width(visible_count), _WINDOW_HEIGHT)

    def _build_collectors(self, *, collector_manager: CollectorManager | None = None) -> None:
        if collector_manager is None:
            collectors = []
            if SHOW_CLAUDE_IN_UI:
                collectors.append(ClaudeBridgeCollector())
            collectors.extend(
                [
                    CodexAppServerCollector(),
                    GrokCollector(),
                    OpenRouterCollector(secret_store=self.secret_store),
                    DeepSeekCollector(secret_store=self.secret_store),
                ]
            )
            collector_manager = CollectorManager(collectors)
        self.collector_manager = collector_manager
        self.collector_manager.register_callback(self._handle_result)

    def _build_timer(self) -> None:
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(600 * 1000)
        self.refresh_timer.timeout.connect(self.refresh_all)

    def _apply_settings(self) -> None:
        settings = self.settings_store.load()
        enable_auto = bool(settings.get("auto_refresh", True))
        if enable_auto:
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

    def refresh_all(self) -> None:
        for key, card in self.cards.items():
            if SHOW_CLAUDE_IN_UI or not _is_claude_card(key):
                card.set_loading()
        self.collector_manager.refresh()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            secret_store=self.secret_store,
            settings_store=self.settings_store,
            show_claude_auth=SHOW_CLAUDE_IN_UI,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_settings()

    def _handle_result(self, result) -> None:
        cards = [
            card
            for key, card in self.cards.items()
            if key == result.provider_id or key.startswith(f"{result.provider_id}_")
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
