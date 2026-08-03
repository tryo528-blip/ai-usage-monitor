from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, UsageSnapshot
from ai_usage_monitor.infrastructure.secret_store import SecretStore

from .base import Collector


class DeepSeekCollector(Collector):
    provider_id = "deepseek"
    provider_name = "DeepSeek"

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self.secret_store = secret_store or SecretStore()

    def is_configured(self) -> bool:
        return bool(self.secret_store.get("deepseek.api_key"))

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        api_key = self.secret_store.get("deepseek.api_key")
        if not api_key:
            return self._build_snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message="DeepSeek API 키가 설정되지 않았습니다.",
                collected_at=now,
                error_code="NOT_CONFIGURED",
            )

        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get("https://api.deepseek.com/user/balance", headers=headers)
                if response.status_code in {401, 403}:
                    return self._build_snapshot(
                        status=ProviderStatus.AUTH_REQUIRED,
                        message="DeepSeek 인증이 필요합니다.",
                        collected_at=now,
                        error_code="AUTH_FAILED",
                    )
                if response.status_code == 402:
                    return self._build_snapshot(
                        status=ProviderStatus.CRITICAL,
                        message="DeepSeek 잔액이 부족합니다.",
                        collected_at=now,
                        error_code="INSUFFICIENT_BALANCE",
                    )
                if response.status_code == 429:
                    return self._build_snapshot(
                        status=ProviderStatus.WARNING,
                        message="DeepSeek 한도에 도달했습니다.",
                        collected_at=now,
                        error_code="RATE_LIMITED",
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="DeepSeek 응답이 늦게 도착했습니다.",
                collected_at=now,
                error_code="NETWORK_TIMEOUT",
            )
        except httpx.HTTPError:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="DeepSeek 연결 오류입니다.",
                collected_at=now,
                error_code="NETWORK_ERROR",
            )
        except ValueError:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="DeepSeek 응답 형식이 올바르지 않습니다.",
                collected_at=now,
                error_code="INVALID_RESPONSE",
            )

        balances = []
        status = ProviderStatus.OK
        for item in payload.get("data", []):
            if item.get("currency") is None:
                continue
            if item.get("is_available") is False:
                status = ProviderStatus.CRITICAL
            balances.append(
                CreditBalance(
                    currency=item.get("currency", "USD"),
                    total=self._parse_decimal(item.get("total")),
                    remaining=self._parse_decimal(item.get("remaining")),
                    used=self._parse_decimal(item.get("used")),
                    granted=self._parse_decimal(item.get("granted")),
                    topped_up=self._parse_decimal(item.get("topped_up")),
                )
            )

        return self._build_snapshot(
            status=status,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            balances=balances,
        )

    def _build_snapshot(
        self,
        *,
        status: ProviderStatus,
        message: str,
        collected_at: datetime,
        error_code: str | None = None,
        last_success_at: datetime | None = None,
        balances: list[CreditBalance] | None = None,
    ) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=status,
            collected_at=collected_at,
            last_success_at=last_success_at,
            stale_after_seconds=900,
            quota_windows=[],
            balances=balances or [],
            message=message,
            error_code=error_code,
        )

    @staticmethod
    def _parse_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float, str)):
            try:
                return Decimal(str(value))
            except Exception:
                return None
        return None
