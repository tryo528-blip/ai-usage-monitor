from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot
from ai_usage_monitor.infrastructure.database import UsageDatabase


def test_usage_database_persists_snapshot(tmp_path) -> None:
    db = UsageDatabase(tmp_path / "usage.db")
    now = datetime.now(timezone.utc)
    snapshot = UsageSnapshot(
        provider_id="openrouter",
        provider_name="OpenRouter",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=now,
        last_success_at=now,
        quota_windows=[
            QuotaWindow(
                key="daily",
                label="일간",
                used_percent=42.0,
                used_value=Decimal("42"),
                limit_value=Decimal("100"),
                remaining_value=Decimal("58"),
                unit="tokens",
            )
        ],
        balances=[CreditBalance(currency="USD", remaining=Decimal("7.84"))],
    )

    snapshot_id = db.save_snapshot(snapshot)
    assert snapshot_id > 0
