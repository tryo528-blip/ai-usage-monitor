from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
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
        self.setFixedSize(360, 220)
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
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(4)
        title = QLabel("AI Usage Monitor")
        self.refresh_button = QPushButton("새로고침")
        self.settings_button = QPushButton("설정")
        self.refresh_button.setFixedHeight(24)
        self.settings_button.setFixedHeight(24)
        top_bar.addWidget(title)
        top_bar.addStretch(1)
        top_bar.addWidget(self.refresh_button)
        top_bar.addWidget(self.settings_button)
        layout.addLayout(top_bar)

        rows_layout = QVBoxLayout()
        rows_layout.setSpacing(3)
        self.cards = {
            "claude": ProviderCard(
                "클로드",
                summary_type="quota",
                quota_fields=(("weekly", "주간 사용량"), ("five_hour", "5시간 사용량")),
            ),
            "codex": ProviderCard(
                "코덱스",
                summary_type="quota",
                quota_fields=(("weekly", "주간 사용량"),),
            ),
            "grok": ProviderCard(
                "그록",
                summary_type="quota",
                quota_fields=(("weekly", "주간 사용량"),),
            ),
            "openrouter": ProviderCard("오픈라우터", summary_type="balance"),
            "deepseek": ProviderCard("딥시크", summary_type="balance"),
        }
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
        card = self.cards.get(result.provider_id)
        if card is None:
            return

        snapshot = result.snapshot
        normalized_status = determine_status(snapshot)
        if normalized_status != snapshot.status:
            snapshot = snapshot.model_copy(update={"status": normalized_status})

        card.set_snapshot(snapshot)
        try:
            self.database.save_snapshot(snapshot)
        except Exception:
            card.set_error("SQLite 저장 실패")

    def _set_font_10(self) -> None:
        font = QFont(self.font())
        font.setPointSize(10)
        self.setFont(font)
