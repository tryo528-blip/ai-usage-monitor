from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
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
        self.setFixedSize(260, 284)
        self._set_font_10()

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
        if self.startup_refresh:
            QTimer.singleShot(0, self.refresh_all)

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setFont(self.font())
        root.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(2)
        title = QLabel("AI Usage Monitor")
        self.refresh_button = QPushButton("새로고침")
        self.settings_button = QPushButton("설정")
        self.refresh_button.setFixedHeight(22)
        self.settings_button.setFixedHeight(22)
        top_bar.addWidget(title)
        top_bar.addStretch(1)
        top_bar.addWidget(self.refresh_button)
        top_bar.addWidget(self.settings_button)
        layout.addLayout(top_bar)

        rows_layout = QHBoxLayout()
        rows_layout.setSpacing(4)
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
        self.cards["claude"].title_label.setText("Claude")
        self.cards["claude_5h"].title_label.setText("Claude")
        self.cards["codex"].title_label.setText("Codex")
        self.cards["grok"].title_label.setText("Grok")
        self.cards["openrouter"].title_label.setText("O.R")
        self.cards["deepseek"].title_label.setText("DSeek")
        for card in self.cards.values():
            rows_layout.addWidget(card)
        layout.addLayout(rows_layout)

        self.setCentralWidget(root)

    def _build_collectors(self, *, collector_manager: CollectorManager | None = None) -> None:
        if collector_manager is None:
            collectors = [
                ClaudeBridgeCollector(),
                CodexAppServerCollector(),
                GrokCollector(),
                OpenRouterCollector(secret_store=self.secret_store),
                DeepSeekCollector(secret_store=self.secret_store),
            ]
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
        for card in self.cards.values():
            card.set_loading()
        self.collector_manager.refresh()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(secret_store=self.secret_store, settings_store=self.settings_store)
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
