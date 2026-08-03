from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot
from ai_usage_monitor.services.status_policy import determine_status


def test_status_policy_thresholds() -> None:
    now = datetime.now(timezone.utc)
    snapshot = UsageSnapshot(
        provider_id="openrouter",
        provider_name="OpenRouter",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.OK,
        collected_at=now,
        quota_windows=[QuotaWindow(key="weekly", label="주간", used_percent=79.9)],
    )
    assert determine_status(snapshot) == ProviderStatus.OK

    snapshot.quota_windows[0].used_percent = 80.0
    assert determine_status(snapshot) == ProviderStatus.WARNING

    snapshot.quota_windows[0].used_percent = 94.9
    assert determine_status(snapshot) == ProviderStatus.WARNING

    snapshot.quota_windows[0].used_percent = 95.0
    assert determine_status(snapshot) == ProviderStatus.CRITICAL

    snapshot.balances = [CreditBalance(currency="USD", remaining=Decimal("0"))]
    assert determine_status(snapshot) == ProviderStatus.CRITICAL


def test_status_policy_preserves_explicit_severity() -> None:
    now = datetime.now(timezone.utc)
    snapshot = UsageSnapshot(
        provider_id="openrouter",
        provider_name="OpenRouter",
        source_type=SourceType.OFFICIAL_API,
        status=ProviderStatus.WARNING,
        collected_at=now,
        quota_windows=[QuotaWindow(key="weekly", label="주간", used_percent=50.0)],
    )
    assert determine_status(snapshot) == ProviderStatus.WARNING

    snapshot.status = ProviderStatus.CRITICAL
    assert determine_status(snapshot) == ProviderStatus.CRITICAL
