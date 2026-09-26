from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from ai_usage_monitor.collectors.antyg_bridge import AntigravityCollector
from ai_usage_monitor.collectors.base import Collector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, UsageSnapshot
from ai_usage_monitor.domain.providers import (
    PROVIDER_CARD_SCHEMA_SETTING,
    PROVIDER_CARD_SCHEMA_VERSION,
)
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectorManager
from ai_usage_monitor.ui.api_key_dialogs import ApiKeyDeleteDialog, ApiKeyInputDialog
from ai_usage_monitor.ui.fonts import PRETENDARD_FAMILY
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

    titles = [card.short_name for card in window.cards.values()]
    assert titles == ["C5", "CW", "FW", "G5", "GW", "GR", "A5", "AW", "OR"]
    assert [card.title_label.text() for card in window.cards.values()] == titles
    full_names = [card.full_name_label.text() for card in window.cards.values()]
    assert full_names == [
        "Claude 5h",
        "Claude Weekly",
        "Fable Weekly",
        "Codex 5h",
        "Codex Weekly",
        "xAI Grok Weekly",
        "Antigravity 5h",
        "Antigravity Weekly",
        "OpenRouter",
    ]
    visible_titles = [card.short_name for card in window.cards.values() if card.isVisible()]
    assert visible_titles == titles
    assert window.cards["claude_fable"].quota_fields == (("weekly_fable", "Fable 주간 사용량"),)
    assert window.cards["codex_5h"].quota_fields == (("five_hour", "5시간 사용량"),)
    assert window.cards["claude_5h"].quota_fields == (("five_hour", "5시간 사용량"),)
    assert window.cards["codex"].quota_fields == (("weekly", "주간 사용량"),)
    assert window.cards["antyg_5h"].quota_fields == (("five_hour", "5시간 사용량"),)
    assert window.cards["antyg"].summary_type == "quota"
    assert window.cards["antyg"].quota_fields == (("weekly", "주간 사용량"),)
    assert window.cards["antyg"].omit_missing_quota is True
    assert window.cards["openrouter"].balance_display == "amount"
    assert [collector.provider_id for collector in window.collector_manager.collectors] == [
        "codex",
        "grok",
        "claude",
        "antyg",
        "openrouter",
    ]
    assert isinstance(window.collector_manager.collectors[-2], AntigravityCollector)
    assert isinstance(window.collector_manager.collectors[-1], OpenRouterCollector)
    # 9 cards of 68px, four same-provider gaps of 5px (C5-CW-FW, G5-GW, A5-AW),
    # four group gaps of 12px, and 14px margins on both sides.
    assert window.size().width() == 9 * 68 + 4 * 5 + 4 * 12 + 2 * 14
    assert window.size().height() == 172
    for button in (
        window.refresh_button,
        window.settings_button,
        window.minimize_button,
        window.close_button,
    ):
        assert button.size().width() == button.size().height() == 28
        assert not button.icon().isNull()
    assert window.refresh_button.toolTip() == "새로고침"
    assert window.settings_button.toolTip() == "설정"
    assert window.settings_button.y() == window.refresh_button.y()
    assert window.title_label.text() == "AI Usage"
    assert window.brand_widget.isVisible()


def test_main_window_applies_visible_provider_selection(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(
        {
            "auto_refresh": False,
            PROVIDER_CARD_SCHEMA_SETTING: PROVIDER_CARD_SCHEMA_VERSION,
            "visible_providers": ["grok", "openrouter"],
        }
    )
    window = MainWindow(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
        database=UsageDatabase(tmp_path / "usage.db"),
        startup_refresh=False,
    )
    qtbot.addWidget(window)
    window.show()

    assert [card.short_name for card in window.cards.values() if card.isVisible()] == [
        "GR",
        "OR",
    ]
    # The default tray (C5 / CW / FW) keeps the Claude collector running even
    # though no Claude card is visible in the window.
    assert [collector.provider_id for collector in window.collector_manager.collectors] == [
        "grok",
        "claude",
        "openrouter",
    ]
    assert window.size().width() == 240
    assert window.brand_widget.isVisible()

    settings_store.save(
        {
            "auto_refresh": False,
            PROVIDER_CARD_SCHEMA_SETTING: PROVIDER_CARD_SCHEMA_VERSION,
            "visible_providers": ["codex"],
        }
    )
    assert window._apply_settings() is True
    assert [card.short_name for card in window.cards.values() if card.isVisible()] == [
        "GW",
    ]
    assert [collector.provider_id for collector in window.collector_manager.collectors] == [
        "codex",
        "claude",
    ]


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
        lambda: card.value_label.text() == "$0",
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


def test_settings_dialog_saves_visible_provider_selection(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(
        {
            "auto_refresh": False,
            PROVIDER_CARD_SCHEMA_SETTING: PROVIDER_CARD_SCHEMA_VERSION,
            "visible_providers": ["codex", "antyg"],
        }
    )
    dialog = SettingsDialog(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
    )
    qtbot.addWidget(dialog)

    assert dialog.provider_checkboxes["codex"].isChecked()
    assert not dialog.provider_checkboxes["grok"].isChecked()
    assert dialog.provider_checkboxes["antyg"].isChecked()
    assert not dialog.provider_checkboxes["codex_5h"].isChecked()
    assert not dialog.provider_checkboxes["antyg_5h"].isChecked()
    assert "openrouter" in dialog.provider_checkboxes
    assert not dialog.provider_checkboxes["openrouter"].isChecked()
    assert dialog.font().family() == PRETENDARD_FAMILY
    assert not dialog.font().bold()
    dialog.ensurePolished()
    for label in dialog.findChildren(QLabel):
        label.ensurePolished()
        assert label.font().family() == PRETENDARD_FAMILY
        assert not label.font().bold()
    for button in (
        dialog.close_button,
        dialog.key_input_button,
        dialog.key_delete_button,
        dialog.claude_auth_button,
        dialog.grok_auth_button,
        dialog.cancel_button,
        dialog.save_button,
    ):
        button.ensurePolished()
        assert button.font().family() == PRETENDARD_FAMILY
        assert not button.font().bold()
    assert dialog.size().height() == 744

    dialog.provider_checkboxes["grok"].setChecked(True)
    dialog.save_settings()

    assert settings_store.load()["visible_providers"] == ["codex", "grok", "antyg"]
    assert settings_store.load()[PROVIDER_CARD_SCHEMA_SETTING] == PROVIDER_CARD_SCHEMA_VERSION


def test_settings_dialog_save_does_not_touch_existing_api_key(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    fake_secret_store = FakeSecretStore()
    fake_secret_store.set("openrouter.management_key", "existing-secret")
    settings_store = SettingsStore(tmp_path / "settings.json")

    dialog = SettingsDialog(
        secret_store=fake_secret_store,
        settings_store=settings_store,
    )
    dialog.save_settings()

    assert fake_secret_store.get("openrouter.management_key") == "existing-secret"


def test_settings_dialog_can_be_dragged_from_header(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        secret_store=FakeSecretStore(),
        settings_store=SettingsStore(tmp_path / "settings.json"),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    before = dialog.pos()

    QTest.mousePress(
        dialog,
        Qt.MouseButton.LeftButton,
        pos=QPoint(30, 30),
    )
    QTest.mouseMove(dialog, QPoint(80, 60), delay=20)
    QTest.mouseRelease(
        dialog,
        Qt.MouseButton.LeftButton,
        pos=QPoint(80, 60),
    )

    assert dialog.pos() == before + QPoint(50, 30)


def test_api_key_input_dialog_saves_selected_model_key(qtbot) -> None:
    QApplication.instance() or QApplication([])
    fake_secret_store = FakeSecretStore()
    dialog = ApiKeyInputDialog(secret_store=fake_secret_store)
    qtbot.addWidget(dialog)

    dialog.model_combo.setCurrentText("Grok")
    dialog.api_key_input.setText("grok-secret")
    dialog.save_key()

    assert fake_secret_store.get("grok.api_key") == "grok-secret"
    assert fake_secret_store.get("codex.api_key") is None


def test_api_key_input_dialog_saves_openrouter_management_key(qtbot) -> None:
    QApplication.instance() or QApplication([])
    fake_secret_store = FakeSecretStore()
    dialog = ApiKeyInputDialog(secret_store=fake_secret_store)
    qtbot.addWidget(dialog)

    dialog.model_combo.setCurrentText("OpenRouter")
    assert dialog.test_button.isEnabled()
    assert "Management Key" in dialog.storage_note.text()
    dialog.api_key_input.setText("openrouter-management-secret")
    dialog.save_key()

    assert fake_secret_store.get("openrouter.management_key") == "openrouter-management-secret"


def test_api_key_dialog_exposes_every_provider_and_uses_regular_pretendard(
    qtbot,
) -> None:
    QApplication.instance() or QApplication([])
    dialog = ApiKeyInputDialog(secret_store=FakeSecretStore())
    qtbot.addWidget(dialog)

    assert [dialog.model_combo.itemText(index) for index in range(dialog.model_combo.count())] == [
        "Codex",
        "Grok",
        "OpenRouter",
        "Claude",
        "Antigravity",
    ]
    assert dialog.font().family() == PRETENDARD_FAMILY
    assert not dialog.font().bold()
    dialog.ensurePolished()
    for label in dialog.findChildren(QLabel):
        label.ensurePolished()
        assert label.font().family() == PRETENDARD_FAMILY
        assert not label.font().bold()
    for widget in (
        dialog.model_combo,
        dialog.api_key_input,
        dialog.cancel_button,
        dialog.test_button,
        dialog.save_button,
    ):
        widget.ensurePolished()
        assert widget.font().family() == PRETENDARD_FAMILY
        assert not widget.font().bold()


def test_api_key_delete_dialog_deletes_only_selected_model_key(qtbot) -> None:
    QApplication.instance() or QApplication([])
    fake_secret_store = FakeSecretStore()
    fake_secret_store.set("grok.api_key", "grok-secret")
    fake_secret_store.set("claude.api_key", "claude-secret")
    dialog = ApiKeyDeleteDialog(secret_store=fake_secret_store)
    qtbot.addWidget(dialog)

    dialog.model_combo.setCurrentText("Claude")
    assert dialog.delete_button.isEnabled()
    dialog.delete_key()

    assert fake_secret_store.get("claude.api_key") is None
    assert fake_secret_store.get("grok.api_key") == "grok-secret"


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
