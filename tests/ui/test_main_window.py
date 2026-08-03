from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectorManager
from ai_usage_monitor.ui.main_window import MainWindow
from ai_usage_monitor.ui.settings_dialog import SettingsDialog


class CriticalCollector(Collector):
    provider_id = "openrouter"
    provider_name = "OpenRouter"

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=ProviderStatus.OK,
            collected_at=datetime.now(timezone.utc),
            quota_windows=[
                QuotaWindow(key="daily", label="Daily", used_percent=96.0),
            ],
            message="quota refreshed",
        )


class CountingCollector(CriticalCollector):
    def __init__(self) -> None:
        self.calls = 0

    def collect(self) -> UsageSnapshot:
        self.calls += 1
        return super().collect()


def test_main_window_builds_cards(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = MainWindow(
        secret_store=FakeSecretStore(),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        database=UsageDatabase(tmp_path / "usage.db"),
        startup_refresh=False,
    )
    qtbot.addWidget(window)
    titles = [card.title_label.text() for card in window.cards.values()]
    assert len(window.cards) == 6
    assert "Mock" not in titles
    assert "Grok" in titles
    assert "Gemini" in titles


def test_main_window_refreshes_card_applies_policy_and_saves_sqlite(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    database_path = tmp_path / "usage.db"
    manager = CollectorManager([CriticalCollector()])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save({"auto_refresh": False})
    window = MainWindow(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
        database=UsageDatabase(database_path),
        collector_manager=manager,
        startup_refresh=False,
    )
    qtbot.addWidget(window)

    window.refresh_all()
    card = window.cards["openrouter"]
    qtbot.waitUntil(
        lambda: (
            card.progress_bar.value() == 96
            and card.status_label.text().endswith(ProviderStatus.CRITICAL.value)
        ),
        timeout=5000,
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT provider_id, status, message FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row == ("openrouter", ProviderStatus.CRITICAL.value, "quota refreshed")


def test_main_window_startup_refresh_false_does_not_collect(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    collector = CountingCollector()
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save({"auto_refresh": False})
    window = MainWindow(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
        database=UsageDatabase(tmp_path / "usage.db"),
        collector_manager=CollectorManager([collector]),
        startup_refresh=False,
    )
    qtbot.addWidget(window)

    qtbot.wait(100)

    assert collector.calls == 0


def test_settings_dialog_keeps_existing_keyring_value_on_blank_input(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    fake_secret_store = FakeSecretStore()
    fake_secret_store.set("openrouter.api_key", "existing-secret")
    settings_store = SettingsStore(tmp_path / "settings.json")

    dialog = SettingsDialog(
        secret_store=fake_secret_store,
        settings_store=settings_store,
    )
    dialog.openrouter_key.setText("")
    dialog.save_settings()

    assert fake_secret_store.get("openrouter.api_key") == "existing-secret"
