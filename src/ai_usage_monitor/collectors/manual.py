from __future__ import annotations

from datetime import datetime, timezone

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import UsageSnapshot

from .base import Collector


class ManualCollector(Collector):
    provider_id = "manual"
    provider_name = "Grok / Gemini"

    def __init__(self, provider_id: str, provider_name: str) -> None:
        self.provider_id = provider_id
        self.provider_name = provider_name

    def is_configured(self) -> bool:
        return True

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.MANUAL,
            status=ProviderStatus.MANUAL,
            collected_at=now,
            last_success_at=now,
            message="수동 입력 카드",
        )
