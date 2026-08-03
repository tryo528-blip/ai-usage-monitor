from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.ui.main_window import MainWindow
from ai_usage_monitor.ui.settings_dialog import SettingsDialog


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
