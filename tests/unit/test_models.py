from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot


def test_usage_snapshot_model_accepts_decimal_values() -> None:
    snapshot = UsageSnapshot(
        provider_id="openrouter",
        provider_name="OpenRouter",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=datetime.now(timezone.utc),
        quota_windows=[
            QuotaWindow(
                key="daily",
                label="일간 사용량",
                used_percent=10.0,
                used_value=Decimal("10"),
                limit_value=Decimal("100"),
                remaining_value=Decimal("90"),
                unit="tokens",
            )
        ],
        balances=[CreditBalance(currency="USD", remaining=Decimal("7.84"))],
    )

    assert snapshot.quota_windows[0].used_percent == 10.0
    assert snapshot.balances[0].currency == "USD"
