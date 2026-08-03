from __future__ import annotations

from datetime import datetime, timezone

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import UsageSnapshot

from .base import Collector


class ClaudeBridgeCollector(Collector):
    provider_id = "claude"
    provider_name = "Claude"

    def is_configured(self) -> bool:
        return False

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.LOCAL_BRIDGE,
            status=ProviderStatus.UNAVAILABLE,
            collected_at=now,
            last_success_at=None,
            stale_after_seconds=900,
            message="Claude statusline bridge is not implemented in this phase.",
            error_code="LOCAL_BRIDGE_MISSING",
        )
