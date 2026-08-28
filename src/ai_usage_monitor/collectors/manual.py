from __future__ import annotations

from datetime import datetime, timezone

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import UsageSnapshot
from ai_usage_monitor.infrastructure.secret_store import SecretStore

from .base import Collector


class ManualCollector(Collector):
    """Keep a selectable provider visible until its real collector exists."""

    provider_id = "manual"
    provider_name = "Grok / Gemini"

    def __init__(
        self,
        provider_id: str,
        provider_name: str,
        *,
        secret_store: SecretStore | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.secret_store = secret_store
        self.secret_key = secret_key

    def is_configured(self) -> bool:
        if self.secret_store is None or self.secret_key is None:
            return True
        try:
            return bool(self.secret_store.get(self.secret_key))
        except Exception:
            return False

    def _missing_key_snapshot(self, now: datetime) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.MANUAL,
            status=ProviderStatus.AUTH_REQUIRED,
            collected_at=now,
            message=f"{self.provider_name} API 키가 없습니다.",
            error_code="NOT_CONFIGURED",
        )

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        if not self.is_configured():
            return self._missing_key_snapshot(now)
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.MANUAL,
            status=ProviderStatus.MANUAL,
            collected_at=now,
            last_success_at=now,
            message="키는 저장됐지만 사용량 수집기는 아직 연결되지 않았습니다.",
        )
