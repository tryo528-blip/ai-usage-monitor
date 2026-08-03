from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot

from .base import Collector


class MockCollector(Collector):
    provider_id = "mock"
    provider_name = "Mock"

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.MOCK,
            status=ProviderStatus.OK,
            collected_at=now,
            last_success_at=now,
            stale_after_seconds=900,
            quota_windows=[
                QuotaWindow(
                    key="mock-window",
                    label="Mock window",
                    used_percent=45.0,
                    used_value=Decimal("45"),
                    limit_value=Decimal("100"),
                    remaining_value=Decimal("55"),
                    unit="units",
                    window_minutes=60,
                    resets_at=now + timedelta(minutes=30),
                )
            ],
            balances=[CreditBalance(currency="USD", total=Decimal("100"), remaining=Decimal("55"))],
            message="Mock snapshot",
        )
