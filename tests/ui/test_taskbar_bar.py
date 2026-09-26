from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ai_usage_monitor.app import should_show_window, signal_running_instance
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot
from ai_usage_monitor.domain.providers import (
    PROVIDER_CARD_SCHEMA_SETTING,
    PROVIDER_CARD_SCHEMA_VERSION,
    TASKBAR_PROVIDERS_SETTING,
    get_taskbar_provider_ids,
)
from ai_usage_monitor.infrastructure.database import UsageDatabase
from ai_usage_monitor.infrastructure.secret_store import FakeSecretStore
from ai_usage_monitor.infrastructure.settings_store import SettingsStore
from ai_usage_monitor.services.collector_manager import CollectionResult, CollectorManager
from ai_usage_monitor.ui import theme
from ai_usage_monitor.ui.main_window import MainWindow
from ai_usage_monitor.ui.settings_dialog import SettingsDialog
from ai_usage_monitor.ui.taskbar_bar import taskbar_rect
from ai_usage_monitor.ui.theme import AlertLevel


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


def test_taskbar_selection_defaults_to_claude_session_weekly_and_fable() -> None:
    assert get_taskbar_provider_ids({}) == ("claude_5h", "claude", "claude_fable")
    assert get_taskbar_provider_ids({"visible_providers": ["grok"]}) == (
        "claude_5h",
        "claude",
        "claude_fable",
    )


def test_taskbar_selection_keeps_saved_order_drops_unknown_and_caps_at_three() -> None:
    settings = {
        TASKBAR_PROVIDERS_SETTING: ["antyg_5h", "nope", "codex", "antyg_5h", "grok", "kimi3"]
    }
    assert get_taskbar_provider_ids(settings) == ("antyg_5h", "codex", "grok")
    assert get_taskbar_provider_ids({TASKBAR_PROVIDERS_SETTING: []}) == ()


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


def test_taskbar_bar_follows_selected_cards_even_when_hidden(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(
        tmp_path,
        {"visible_providers": ["grok"], TASKBAR_PROVIDERS_SETTING: ["antyg_5h", "antyg"]},
    )
    qtbot.addWidget(window)

    assert list(window.taskbar_bar.items) == ["antyg_5h", "antyg"]
    assert window.taskbar_bar.isVisible()
    assert window.tracked_provider_ids == ("grok", "antyg_5h", "antyg")
    assert window.taskbar_bar.text() == "A5 --  AW --"

    window._handle_result(CollectionResult("antyg", _antigravity_snapshot()))

    assert window.taskbar_bar.text() == "A5 03  AW 78"
    tooltip = window.taskbar_bar.toolTip()
    assert tooltip.startswith("A503 · Antigravity 5h 3%")
    assert "AW78 · Antigravity Weekly 78%" in tooltip
    assert window.taskbar_bar.items["antyg_5h"].level == AlertLevel.CRITICAL


def test_saving_settings_updates_taskbar_selection(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    assert list(window.taskbar_bar.items) == ["claude_5h", "claude", "claude_fable"]

    dialog = SettingsDialog(secret_store=FakeSecretStore(), settings_store=window.settings_store)
    qtbot.addWidget(dialog)
    assert [combo.currentData() for combo in dialog.taskbar_combos] == [
        "claude_5h",
        "claude",
        "claude_fable",
    ]
    dialog.taskbar_combos[0].setCurrentIndex(dialog.taskbar_combos[0].findData("codex_5h"))
    dialog.taskbar_combos[1].setCurrentIndex(dialog.taskbar_combos[1].findData("codex_5h"))
    dialog.taskbar_combos[2].setCurrentIndex(dialog.taskbar_combos[2].findData("openrouter"))
    dialog.save_settings()

    assert window.settings_store.load()[TASKBAR_PROVIDERS_SETTING] == ["codex_5h", "openrouter"]
    assert window._apply_settings() is True
    assert list(window.taskbar_bar.items) == ["codex_5h", "openrouter"]
    assert window.tracked_provider_ids == ("codex_5h", "grok", "openrouter")

    window.settings_store.save(window.settings_store.load() | {TASKBAR_PROVIDERS_SETTING: []})
    window._apply_settings()
    assert not window.taskbar_bar.active
    assert not window.taskbar_bar.isVisible()


def test_close_hides_window_while_taskbar_bar_shows_and_quit_closes(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    window.close()
    assert not window.isVisible()
    assert window.taskbar_bar.isVisible()

    QTest.mouseClick(window.taskbar_bar, Qt.MouseButton.LeftButton)
    assert window.isVisible()

    window.quit_app()
    assert not window.isVisible()
    assert not window.taskbar_bar.isVisible()


def test_session_end_lets_close_through(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    window.show()

    window.allow_close()
    window.close()

    assert not window.isVisible()


def test_dragging_the_bar_moves_it_and_remembers_offset(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    bar = window.taskbar_bar
    start_x = bar.x()

    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(10, 5))
    QTest.mouseMove(bar, QPoint(70, 5))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(70, 5))

    assert bar.x() == start_x + 60
    assert window.settings_store.load()["taskbar_offset_x"] == bar.offset_x
    assert not window.isVisible()  # a drag is not a click


def test_taskbar_rect_uses_reserved_strip_or_bottom_fallback() -> None:
    screen = QRect(0, 0, 1920, 1080)
    assert taskbar_rect(screen, QRect(0, 0, 1920, 1032)) == QRect(0, 1032, 1920, 48)
    assert taskbar_rect(screen, QRect(0, 40, 1920, 1040)) == QRect(0, 0, 1920, 40)
    assert taskbar_rect(screen, screen) == QRect(0, 1032, 1920, 48)


def test_hidden_start_only_when_taskbar_readout_exists() -> None:
    assert should_show_window(False, True)
    assert not should_show_window(True, True)
    assert should_show_window(True, False)


def test_second_launch_reaches_running_instance(qtbot) -> None:
    from PySide6.QtNetwork import QLocalServer

    QApplication.instance() or QApplication([])
    key = "AIUsageMonitor.test-instance"
    assert not signal_running_instance(key)

    QLocalServer.removeServer(key)
    server = QLocalServer()
    assert server.listen(key)
    try:
        assert signal_running_instance(key)
    finally:
        server.close()


def test_taskbar_value_is_always_two_digits(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["claude_5h", "claude", "claude_fable"]})
    qtbot.addWidget(window)
    now = datetime.now(timezone.utc)
    snapshot = UsageSnapshot(
        provider_id="claude",
        provider_name="Claude",
        source_type=SourceType.LOCAL_BRIDGE,
        status=ProviderStatus.OK,
        collected_at=now,
        quota_windows=[
            QuotaWindow(key="five_hour", label="5h", used_percent=10),
            QuotaWindow(key="weekly", label="weekly", used_percent=93),
            QuotaWindow(key="weekly_fable", label="fable", used_percent=0),
        ],
    )

    window._handle_result(CollectionResult("claude", snapshot))

    assert [window.cards[key].compact_value() for key in window.taskbar_provider_ids] == [
        "90",
        "07",
        "99",
    ]
    assert window.cards["claude_fable"].value_label.text() == "100%"
    window.cards["grok"].set_loading()
    assert window.cards["grok"].compact_value() == "--"


def test_display_mode_toggle_is_saved_and_falls_back_off_windows(qtbot, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    window = _window(tmp_path, {"visible_providers": ["grok"]})
    qtbot.addWidget(window)
    bar = window.taskbar_bar

    assert bar.mode == "embed"
    # Embedding needs the Windows taskbar; elsewhere the bar stays a window.
    assert not bar.embedded
    assert bar.isVisible()
    assert "띄우기" in bar.mode_action.text()

    bar.mode_action.trigger()

    assert bar.mode == "overlay"
    assert window.settings_store.load()["taskbar_mode"] == "overlay"
    assert "붙이기" in bar.mode_action.text()
    assert bar.isVisible()

    window2 = _window(tmp_path / "second", {"taskbar_mode": "overlay"})
    qtbot.addWidget(window2)
    assert window2.taskbar_bar.mode == "overlay"
