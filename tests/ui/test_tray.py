from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot
from ai_usage_monitor.domain.providers import (
    PROVIDER_CARD_SCHEMA_SETTING,
    PROVIDER_CARD_SCHEMA_VERSION,
    TRAY_PROVIDERS_SETTING,
    get_tray_provider_ids,
)
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectionResult, CollectorManager
from ai_usage_monitor.ui import theme
from ai_usage_monitor.ui.main_window import MainWindow
from ai_usage_monitor.ui.settings_dialog import SettingsDialog
from ai_usage_monitor.ui.theme import AlertLevel
from ai_usage_monitor.ui.tray import TrayController, render_tray_pixmap


def _antigravity_snapshot() -> UsageSnapshot:
    now = datetime.now(timezone.utc)
    return UsageSnapshot(
        provider_id="antyg",
        provider_name="Antigravity",
        source_type=SourceType.LOCAL_BRIDGE,
        status=ProviderStatus.OK,
        collected_at=now,
        quota_windows=[
            QuotaWindow(
                key="five_hour",
                label="5h",
                used_percent=97,
                resets_at=now + timedelta(minutes=30),
            ),
            QuotaWindow(key="weekly", label="weekly", used_percent=22),
        ],
    )


def _window(tmp_path, settings: dict) -> MainWindow:
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(
        {"auto_refresh": False, PROVIDER_CARD_SCHEMA_SETTING: PROVIDER_CARD_SCHEMA_VERSION}
        | settings
    )
    return MainWindow(
        secret_store=FakeSecretStore(),
        settings_store=settings_store,
        database=UsageDatabase(tmp_path / "usage.db"),
        collector_manager=CollectorManager([]),
        startup_refresh=False,
    )


def test_tray_selection_defaults_to_first_three_measurable_visible_cards() -> None:
    settings = {
        PROVIDER_CARD_SCHEMA_SETTING: PROVIDER_CARD_SCHEMA_VERSION,
        "visible_providers": ["zai", "grok", "deepseek", "antyg", "openrouter"],
    }
    assert get_tray_provider_ids(settings) == ("grok", "deepseek", "antyg")


def test_tray_selection_keeps_saved_order_drops_unknown_and_caps_at_three() -> None:
    settings = {TRAY_PROVIDERS_SETTING: ["antyg_5h", "nope", "codex", "antyg_5h", "grok", "kimi3"]}
    assert get_tray_provider_ids(settings) == ("antyg_5h", "codex", "grok")
    assert get_tray_provider_ids({TRAY_PROVIDERS_SETTING: []}) == ()


def test_cards_color_each_window_by_its_own_remaining_quota(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["antyg_5h", "antyg"]})
    qtbot.addWidget(window)

    window._handle_result(CollectionResult("antyg", _antigravity_snapshot()))

    five_hour = window.cards["antyg_5h"]
    weekly = window.cards["antyg"]
    assert five_hour.value_label.text() == "3%"
    assert five_hour.level == AlertLevel.CRITICAL
    assert five_hour.fraction == 0.03
    # A nearly empty 5-hour window must not paint the healthy weekly card red.
    assert weekly.value_label.text() == "78%"
    assert weekly.level == AlertLevel.OK
    assert weekly.fraction == 0.78
    assert five_hour.accent == weekly.accent == theme.PROVIDER_ACCENTS["antyg"]


def test_tray_icons_follow_selected_cards_even_when_hidden(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(
        tmp_path,
        {"visible_providers": ["grok"], TRAY_PROVIDERS_SETTING: ["antyg_5h", "antyg"]},
    )
    qtbot.addWidget(window)

    assert list(window.tray.icons) == ["antyg_5h", "antyg"]
    assert window.tracked_provider_ids == ("grok", "antyg_5h", "antyg")

    window._handle_result(CollectionResult("antyg", _antigravity_snapshot()))

    assert window.cards["antyg_5h"].compact_value() == "3"
    tooltip = window.tray.icons["antyg_5h"].toolTip()
    assert tooltip.startswith("Antigravity 5h  3%")
    assert "초기화" in tooltip
    assert window.tray.icons["antyg"].toolTip().startswith("Antigravity Weekly  78%")
    assert not window.tray.icons["antyg"].icon().isNull()


def test_saving_settings_updates_tray_selection(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    assert list(window.tray.icons) == ["grok"]

    dialog = SettingsDialog(secret_store=FakeSecretStore(), settings_store=window.settings_store)
    qtbot.addWidget(dialog)
    assert [combo.currentData() for combo in dialog.tray_combos] == ["grok", None, None]
    dialog.tray_combos[0].setCurrentIndex(dialog.tray_combos[0].findData("codex_5h"))
    dialog.tray_combos[1].setCurrentIndex(dialog.tray_combos[1].findData("codex_5h"))
    dialog.tray_combos[2].setCurrentIndex(dialog.tray_combos[2].findData("openrouter"))
    dialog.save_settings()

    assert window.settings_store.load()[TRAY_PROVIDERS_SETTING] == ["codex_5h", "openrouter"]
    assert window._apply_settings() is True
    assert list(window.tray.icons) == ["codex_5h", "openrouter"]
    assert window.tracked_provider_ids == ("codex_5h", "grok", "openrouter")


def test_close_hides_to_tray_and_quit_really_closes(qtbot, tmp_path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(TrayController, "is_available", staticmethod(lambda: True))
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    window.close()
    assert not window.isVisible()
    assert list(window.tray.icons) == ["grok"]

    window.toggle_visible()
    assert window.isVisible()

    window.quit_app()
    assert not window.isVisible()


def test_tray_pixmap_draws_number_on_dark_disc(qtbot) -> None:
    QApplication.instance() or QApplication([])
    pixmap = render_tray_pixmap(32, "42", 0.42, "#3ddc97", AlertLevel.OK)
    image = pixmap.toImage()

    assert pixmap.width() == pixmap.height() == 32
    assert image.pixelColor(0, 0).alpha() == 0
    # The arc starts at 12 o'clock and runs clockwise, so the top-right edge
    # is accent colored while the top-left edge still shows the dark track.
    top_right = image.pixelColor(22, 2)
    assert top_right.green() > top_right.red()
    assert QColor(image.pixelColor(9, 2)).lightness() < 80
