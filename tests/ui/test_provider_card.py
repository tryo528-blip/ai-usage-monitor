from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from PySide6.QtWidgets import QApplication

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot
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

    assert card.value_label.text() == "40/100 \uc0ac\uc6a9 / 10/50 \uc0ac\uc6a9"
    assert card.time_label.text() == "13:00"
    assert card.font().pointSize() == 10
    assert card.title_label.font().pointSize() == 8
    assert card.value_label.font().pointSize() == 9
    assert card.size().width() == 62
    assert card.size().height() == 104


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

    assert card.value_label.text() == "NOT\nCONNECTED"
    assert card.value_label.toolTip() == message


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

    assert card.value_label.text() == "63%"
    assert card.value_label.font().pointSize() == 15


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

    assert card.value_label.text() == "67% / 71%"
    assert card.time_label.text() == "17:40"


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


def test_provider_card_shows_placeholder_for_unconnected_model(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard("Z.AI", summary_type="manual")
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="zai",
        provider_name="Z.AI",
        source_type=SourceType.MANUAL,
        status=ProviderStatus.MANUAL,
        collected_at=datetime.now(timezone.utc),
        message="사용량 연동 준비 중",
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "NOT\nCONNECTED"
    assert card.value_label.font().pointSize() == 6
    assert card.value_label.toolTip() == "사용량 연동 준비 중"


def test_provider_card_omits_missing_antigravity_window(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "AntyG",
        summary_type="quota",
        quota_fields=(
            ("five_hour", "5시간 사용량"),
            ("weekly", "주간 사용량"),
        ),
        omit_missing_quota=True,
    )
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="antyg",
        provider_name="Google Antigravity (Gemini)",
        source_type=SourceType.LOCAL_BRIDGE,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(key="weekly", label="주간 사용량", used_percent=2.0),
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "98%"


def test_provider_card_shows_no_credit_on_zero_balance(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard("DSK", summary_type="balance", full_name="DeepSeek")
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="deepseek",
        provider_name="DeepSeek",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.CRITICAL,
        collected_at=datetime.now(timezone.utc),
        balances=[CreditBalance(currency="USD", remaining=Decimal("0"))],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "NO\nCREDIT"
    assert card.window_label.text() == "BAL"
    assert card.full_name_label.isHidden()
    assert card.toolTip() == "DeepSeek"


def test_openrouter_card_shows_remaining_amount_with_two_decimals(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "OR",
        summary_type="balance",
        full_name="OpenRouter",
        balance_display="amount",
    )
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="openrouter",
        provider_name="OpenRouter",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        balances=[
            CreditBalance(
                currency="USD",
                total=Decimal("100.5"),
                used=Decimal("25.75"),
                remaining=Decimal("74.75"),
            )
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "74.75"
    assert card.value_label.font().pointSize() == 12
    assert card.window_label.text() == "USD"
    assert card.value_label.toolTip() == "74.75 USD"


def test_provider_card_distinguishes_missing_key_from_connection_error(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard("DSK", summary_type="balance", full_name="DeepSeek")
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="deepseek",
        provider_name="DeepSeek",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.AUTH_REQUIRED,
        collected_at=datetime.now(timezone.utc),
        message="DeepSeek API 키가 없습니다.",
        error_code="NOT_CONFIGURED",
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "NO\nKEY"
    assert card.value_label.toolTip() == "DeepSeek API 키가 없습니다."


def test_provider_card_shows_no_data_when_requested_window_is_missing(qtbot) -> None:
    QApplication.instance() or QApplication([])
    card = ProviderCard(
        "CDX-5",
        summary_type="quota",
        quota_fields=(("five_hour", "5시간 사용량"),),
        omit_missing_quota=True,
    )
    qtbot.addWidget(card)
    snapshot = UsageSnapshot(
        provider_id="codex",
        provider_name="Codex",
        source_type=SourceType.LOCAL_RPC,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(key="weekly", label="주간 사용량", used_percent=12.2)
        ],
    )

    card.set_snapshot(snapshot)

    assert card.value_label.text() == "NO\nDATA"
