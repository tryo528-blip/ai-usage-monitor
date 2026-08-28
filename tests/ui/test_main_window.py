from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.collectors.antyg_bridge import AntigravityCollector
from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, UsageSnapshot
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectorManager
from ai_usage_monitor.ui.main_window import MainWindow
from ai_usage_monitor.ui.settings_dialog import SettingsDialog


class CriticalCollector(Collector):
    provider_id = "deepseek"
    provider_name = "DeepSeek"

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=ProviderStatus.OK,
            collected_at=datetime.now(timezone.utc),
            balances=[CreditBalance(currency="USD", remaining=0)],
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
    window.show()
    qtbot.waitExposed(window)

    titles = [card.title_label.text() for card in window.cards.values()]
    assert titles == ["CDX", "Grok", "DSeek", "Z.AI", "KIMI3", "CLD5H", "AntyG", "CLD-W"]
    full_names = [card.full_name_label.text() for card in window.cards.values()]
    assert full_names == [
        "Codex",
        "xAI Grok",
        "DeepSeek",
        "Z.AI",
        "Kimi 3",
        "Claude",
        "Google Antigravity (Gemini)",
        "Claude Weekly",
    ]
    visible_titles = [card.title_label.text() for card in window.cards.values() if card.isVisible()]
    assert visible_titles == ["CDX", "Grok", "DSeek", "Z.AI", "KIMI3", "CLD5H", "AntyG"]
    assert window.cards["claude_5h"].quota_fields == (("five_hour", "5시간 사용량"),)
    assert window.cards["codex"].quota_fields == (("weekly", "주간 사용량"),)
    assert window.cards["antyg"].summary_type == "quota"
    assert window.cards["antyg"].quota_fields == (
        ("five_hour", "5시간 사용량"),
        ("weekly", "주간 사용량"),
    )
    assert window.cards["antyg"].omit_missing_quota is True
    assert [collector.provider_id for collector in window.collector_manager.collectors] == [
        "codex",
        "grok",
        "deepseek",
        "zai",
        "kimi3",
        "claude",
        "antyg",
    ]
    assert isinstance(window.collector_manager.collectors[-1], AntigravityCollector)
    assert window.size().width() == 360
    assert window.size().height() == 200
    assert window.refresh_button.size().width() == 62
    assert window.settings_button.size().width() == 38
    assert window.refresh_button.size().height() == 22
    assert window.refresh_button.font().pointSize() == 8
    assert window.settings_button.y() == window.refresh_button.y()
    assert window.subtitle_label.text() == "AI Usage Monitor"


def test_main_window_applies_visible_provider_selection(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save({"auto_refresh": False, "visible_providers": ["grok", "zai"]})
    window = MainWindow(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
        database=UsageDatabase(tmp_path / "usage.db"),
        startup_refresh=False,
    )
    qtbot.addWidget(window)
    window.show()

    assert [card.title_label.text() for card in window.cards.values() if card.isVisible()] == [
        "Grok",
        "Z.AI",
    ]
    assert [collector.provider_id for collector in window.collector_manager.collectors] == [
        "grok",
        "zai",
    ]

    settings_store.save({"auto_refresh": False, "visible_providers": ["codex"]})
    assert window._apply_settings() is True
    assert [card.title_label.text() for card in window.cards.values() if card.isVisible()] == [
        "CDX",
    ]
    assert [collector.provider_id for collector in window.collector_manager.collectors] == ["codex"]


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
    card = window.cards["deepseek"]
    qtbot.waitUntil(
        lambda: card.value_label.text() == "0%",
        timeout=5000,
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT provider_id, status, message FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row == ("deepseek", ProviderStatus.CRITICAL.value, "quota refreshed")


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


def test_settings_dialog_saves_visible_provider_selection(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save({"auto_refresh": False, "visible_providers": ["codex", "antyg"]})
    dialog = SettingsDialog(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
    )
    qtbot.addWidget(dialog)

    assert dialog.provider_checkboxes["codex"].isChecked()
    assert not dialog.provider_checkboxes["grok"].isChecked()
    assert dialog.provider_checkboxes["antyg"].isChecked()
    assert "openrouter" not in dialog.provider_checkboxes

    dialog.provider_checkboxes["grok"].setChecked(True)
    dialog.save_settings()

    assert settings_store.load()["visible_providers"] == ["codex", "grok", "antyg"]


def test_settings_dialog_keeps_existing_deepseek_keyring_value_on_blank_input(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    fake_secret_store = FakeSecretStore()
    fake_secret_store.set("deepseek.api_key", "existing-secret")
    settings_store = SettingsStore(tmp_path / "settings.json")

    dialog = SettingsDialog(
        secret_store=fake_secret_store,
        settings_store=settings_store,
    )
    dialog.deepseek_key.setText("")
    dialog.save_settings()

    assert fake_secret_store.get("deepseek.api_key") == "existing-secret"


def test_settings_dialog_exposes_claude_and_grok_auth_buttons(qtbot, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        secret_store=FakeSecretStore(),
        settings_store=SettingsStore(),
    )
    qtbot.addWidget(dialog)
    launched = []
    monkeypatch.setattr(
        dialog,
        "_start_cli",
        lambda label, command, arguments: launched.append((label, command, arguments)),
    )

    dialog.claude_auth_button.click()
    dialog.grok_auth_button.click()

    assert launched == [
        ("Claude", "claude", ["auth", "login"]),
        ("Grok", "grok", ["login"]),
    ]


def test_settings_dialog_hides_claude_auth_when_disabled(qtbot) -> None:
    QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        secret_store=FakeSecretStore(),
        settings_store=SettingsStore(),
        show_claude_auth=False,
    )
    qtbot.addWidget(dialog)

    assert dialog.claude_auth_button.isHidden()
    assert not dialog.grok_auth_button.isHidden()
