from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, UsageSnapshot
from ai_usage_monitor.infrastructure.secret_store import SecretStore

from .base import Collector


class OpenRouterCollector(Collector):
    provider_id = "openrouter"
    provider_name = "OpenRouter"

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self.secret_store = secret_store or SecretStore()

    def is_configured(self) -> bool:
        return bool(self.secret_store.get("openrouter.management_key"))

    def collect(self) -> UsageSnapshot:
        management_key = self.secret_store.get("openrouter.management_key")
        now = datetime.now(timezone.utc)

        if not management_key:
            return self._build_snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message="OpenRouter Management Key가 설정되지 않았습니다.",
                collected_at=now,
                error_code="MANAGEMENT_KEY_NOT_CONFIGURED",
            )

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={
                        "Authorization": f"Bearer {management_key}",
                        "Accept": "application/json",
                    },
                )
                if response.status_code in {401, 403}:
                    return self._build_snapshot(
                        status=ProviderStatus.AUTH_REQUIRED,
                        message="OpenRouter Management Key 인증이 필요합니다.",
                        collected_at=now,
                        error_code="AUTH_FAILED",
                    )
                if response.status_code == 402:
                    return self._build_snapshot(
                        status=ProviderStatus.CRITICAL,
                        message="OpenRouter 잔액이 부족합니다.",
                        collected_at=now,
                        error_code="INSUFFICIENT_BALANCE",
                    )
                if response.status_code == 429:
                    return self._build_snapshot(
                        status=ProviderStatus.WARNING,
                        message="OpenRouter 요청이 제한되었습니다.",
                        collected_at=now,
                        error_code="RATE_LIMITED",
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="OpenRouter 응답이 늦게 도착했습니다.",
                collected_at=now,
                error_code="NETWORK_TIMEOUT",
            )
        except httpx.HTTPError:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="OpenRouter 연결 오류입니다.",
                collected_at=now,
                error_code="NETWORK_ERROR",
            )
        except ValueError:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="OpenRouter 응답 형식이 올바르지 않습니다.",
                collected_at=now,
                error_code="INVALID_RESPONSE",
            )

        data = payload.get("data", {})
        total_credits = self._parse_decimal(data.get("total_credits"))
        total_usage = self._parse_decimal(data.get("total_usage"))
        if total_credits is None or total_usage is None:
            return self._build_snapshot(
                status=ProviderStatus.ERROR,
                message="OpenRouter 잔액 응답에 필요한 값이 없습니다.",
                collected_at=now,
                error_code="INVALID_RESPONSE",
            )

        remaining = max(total_credits - total_usage, Decimal("0"))
        balance = CreditBalance(
            currency="USD",
            total=total_credits,
            used=total_usage,
            remaining=remaining,
        )
        return self._build_snapshot(
            status=ProviderStatus.OK,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            balances=[balance],
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
