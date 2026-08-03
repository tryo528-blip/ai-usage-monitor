from __future__ import annotations

from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import UsageSnapshot


def determine_status(snapshot: UsageSnapshot) -> ProviderStatus:
    if snapshot.status == ProviderStatus.MANUAL:
        return ProviderStatus.MANUAL
    if snapshot.status in {ProviderStatus.AUTH_REQUIRED, ProviderStatus.UNAVAILABLE}:
        return snapshot.status
    if snapshot.status in {ProviderStatus.ERROR, ProviderStatus.STALE}:
        return snapshot.status

    highest = ProviderStatus.OK
    for quota in snapshot.quota_windows:
        if quota.used_percent is None:
            continue
        if quota.used_percent >= 95:
            return ProviderStatus.CRITICAL
        if quota.used_percent >= 80:
            highest = ProviderStatus.WARNING
    if snapshot.balances:
        for balance in snapshot.balances:
            if balance.remaining is not None and balance.remaining <= 0:
                return ProviderStatus.CRITICAL
    return highest
