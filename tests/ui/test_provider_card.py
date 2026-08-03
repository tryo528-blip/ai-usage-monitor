from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot
from ai_usage_monitor.ui.provider_card import ProviderCard


def test_provider_card_shows_unavailable_for_missing_usage_percent(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard("Provider")
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="provider",
        provider_name="Provider",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[QuotaWindow(key="window", label="Window")],
    )

    card.set_snapshot(snapshot)

    assert card.progress_bar.value() == 0
    assert card.progress_bar.format() == "조회 불가"
    assert "0%" not in card.progress_bar.text()


def test_provider_card_restores_percent_format_for_known_usage(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard("Provider")
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="provider",
        provider_name="Provider",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[QuotaWindow(key="window", label="Window", used_percent=42.5)],
    )

    card.set_snapshot(snapshot)

    assert card.progress_bar.value() == 42
    assert card.progress_bar.format() == "%p%"
