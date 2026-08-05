from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot
from ai_usage_monitor.ui.provider_card import ProviderCard


def test_provider_card_shows_requested_quota_fields_and_reset_time(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "\uacb0\ub85c\ub4dc",
        summary_type="quota",
        quota_fields=(
            ("weekly", "\uc8fc\uac04 \uc0ac\uc6a9\ub7c9"),
            ("five_hour", "5\uc2dc\uac04 \uc0ac\uc6a9\ub7c9"),
        ),
    )
    qtbot.addWidget(card)
    reset_at = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)
    snapshot = UsageSnapshot(
        provider_id="claude",
        provider_name="Claude",
        source_type=SourceType.LOCAL_BRIDGE,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(
                key="weekly",
                label="weekly",
                used_value=Decimal("40"),
                limit_value=Decimal("100"),
                resets_at=reset_at,
            ),
            QuotaWindow(
                key="five_hour",
                label="5-hour",
                used_value=Decimal("10"),
                limit_value=Decimal("50"),
                resets_at=reset_at + timedelta(hours=1),
            ),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "40/100 \uc0ac\uc6a9 / 10/50 \uc0ac\uc6a9 (13:00)"
    assert card.font().pointSize() == 10
    assert card.title_label.font().pointSize() == 8
    assert card.value_label.font().pointSize() == 8


def test_provider_card_shows_only_unavailable_reason_when_data_is_missing(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "\ucf54\ub371\uc2a4",
        summary_type="quota",
        quota_fields=(("weekly", "\uc8fc\uac04 \uc0ac\uc6a9\ub7c9"),),
    )
    qtbot.addWidget(card)
    message = "Codex \uc0ac\uc6a9\ub7c9 \uc870\ud68c \ubd88\uac00"
    snapshot = UsageSnapshot(
        provider_id="codex",
        provider_name="Codex",
        source_type=SourceType.LOCAL_RPC,
        status=ProviderStatus.UNAVAILABLE,
        collected_at=datetime.now(timezone.utc),
        message=message,
        error_code="CODEX_NOT_INSTALLED",
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == message


def test_provider_card_shows_usage_as_percent_when_source_provides_percent(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "\uadf8\ub85d",
        summary_type="quota",
        quota_fields=(("weekly", "\uc8fc\uac04 \uc0ac\uc6a9\ub7c9"),),
    )
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="grok",
        provider_name="Grok",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(key="weekly", label="\uc8fc\uac04 \uc0ac\uc6a9\ub7c9", used_percent=37.5),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "62.5%"


def test_provider_card_compacts_five_hour_and_weekly_percentages(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "\uacb0\ub85c\ub4dc",
        summary_type="quota",
        quota_fields=(
            ("five_hour", "5\uc2dc\uac04 \uc0ac\uc6a9\ub7c9"),
            ("weekly", "\uc8fc\uac04 \uc0ac\uc6a9\ub7c9"),
        ),
    )
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="claude",
        provider_name="Claude",
        source_type=SourceType.LOCAL_BRIDGE,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(
                key="five_hour",
                label="5\uc2dc\uac04 \uc0ac\uc6a9\ub7c9",
                used_percent=33,
                resets_at=datetime(2026, 8, 5, 8, 40, tzinfo=timezone.utc),
            ),
            QuotaWindow(key="weekly", label="\uc8fc\uac04 \uc0ac\uc6a9\ub7c9", used_percent=29),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "67%\n17:40 / 71%"


def test_provider_card_keeps_weekly_usage_when_five_hour_block_is_missing(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "\uacb0\ub85c\ub4dc",
        summary_type="quota",
        quota_fields=(
            ("weekly", "\uc8fc\uac04 \uc0ac\uc6a9\ub7c9"),
            ("five_hour", "5\uc2dc\uac04 \uc0ac\uc6a9\ub7c9"),
        ),
    )
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="claude",
        provider_name="Claude",
        source_type=SourceType.LOCAL_BRIDGE,
        status=ProviderStatus.UNAVAILABLE,
        collected_at=datetime.now(timezone.utc),
        error_code="ACTIVE_BLOCK_MISSING",
        quota_windows=[
            QuotaWindow(
                key="weekly", label="\uc8fc\uac04 \uc0ac\uc6a9\ub7c9", used_value=Decimal("1200")
            ),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "1,200 \uc0ac\uc6a9 / 5H \uc5c6\uc74c"
