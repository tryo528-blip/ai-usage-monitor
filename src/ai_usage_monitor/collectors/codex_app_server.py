from __future__ import annotations

from datetime import datetime, timezone

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import UsageSnapshot

from .base import Collector


class CodexAppServerCollector(Collector):
    provider_id = "codex"
    provider_name = "Codex"

    def is_configured(self) -> bool:
        return False

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.LOCAL_RPC,
            status=ProviderStatus.UNAVAILABLE,
            collected_at=now,
            last_success_at=None,
            stale_after_seconds=900,
            message="Codex App Server JSON-RPC is deferred to Phase 3.",
            error_code="CODEX_NOT_INSTALLED",
        )
