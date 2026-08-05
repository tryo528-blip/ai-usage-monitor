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
        "클로드",
        summary_type="quota",
        quota_fields=(("weekly", "주간 사용량"), ("five_hour", "5시간 사용량")),
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

    assert card.value_label.text() == (
        "주간 사용량: 40/100 사용 (리셋 08-05 12:00 KST) / "
        "5시간 사용량: 10/50 사용 (리셋 08-05 13:00 KST)"
    )
    assert card.font().pointSize() == 10
    assert card.title_label.font().pointSize() == 10
    assert card.value_label.font().pointSize() == 10


def test_provider_card_shows_only_unavailable_reason_when_data_is_missing(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard("코덱스", summary_type="quota", quota_fields=(("weekly", "주간 사용량"),))
    qtbot.addWidget(card)
    message = "Codex 사용량 조회 불가"
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
    card = ProviderCard("그록", summary_type="quota", quota_fields=(("weekly", "주간 사용량"),))
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="grok",
        provider_name="Grok",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(key="weekly", label="주간 사용량", used_percent=37.5),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "주간 사용량: 37.5% 사용"


def test_provider_card_keeps_weekly_usage_when_five_hour_block_is_missing(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "클로드",
        summary_type="quota",
        quota_fields=(("weekly", "주간 사용량"), ("five_hour", "5시간 사용량")),
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
            QuotaWindow(key="weekly", label="주간 사용량", used_value=Decimal("1200")),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "주간 사용량: 1,200 사용 / 5시간 사용량: 활성 블록 없음"
