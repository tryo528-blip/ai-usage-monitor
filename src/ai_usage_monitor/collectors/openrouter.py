from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot
from ai_usage_monitor.infrastructure.secret_store import SecretStore

from .base import Collector


class OpenRouterCollector(Collector):
    provider_id = "openrouter"
    provider_name = "OpenRouter"

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self.secret_store = secret_store or SecretStore()

    def is_configured(self) -> bool:
        return bool(self.secret_store.get("openrouter.api_key"))

    def collect(self) -> UsageSnapshot:
        api_key = self.secret_store.get("openrouter.api_key")
        management_key = self.secret_store.get("openrouter.management_key")
        now = datetime.now(timezone.utc)

        if not api_key:
            return self._build_snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message="API 키가 설정되지 않았습니다.",
                collected_at=now,
                error_code="NOT_CONFIGURED",
            )

        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get("https://openrouter.ai/api/v1/key", headers=headers)
                if response.status_code in {401, 403}:
                    return self._build_snapshot(
                        status=ProviderStatus.AUTH_REQUIRED,
                        message="OpenRouter 인증이 필요합니다.",
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
                        message="OpenRouter 한도에 도달했습니다.",
                        collected_at=now,
                        error_code="RATE_LIMITED",
                    )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data", {})
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

        usage = data.get("usage", {})
        daily_usage = usage.get("daily", {})
        weekly_usage = usage.get("weekly", {})
        monthly_usage = usage.get("monthly", {})

        quota_windows = [
            QuotaWindow(
                key="daily",
                label="일간 사용량",
                used_percent=self._parse_percent(daily_usage),
                used_value=self._parse_decimal(daily_usage.get("used")),
                limit_value=self._parse_decimal(daily_usage.get("limit")),
                remaining_value=self._parse_decimal(daily_usage.get("remaining")),
                unit=daily_usage.get("unit"),
            ),
            QuotaWindow(
                key="weekly",
                label="주간 사용량",
                used_percent=self._parse_percent(weekly_usage),
                used_value=self._parse_decimal(weekly_usage.get("used")),
                limit_value=self._parse_decimal(weekly_usage.get("limit")),
                remaining_value=self._parse_decimal(weekly_usage.get("remaining")),
                unit=weekly_usage.get("unit"),
            ),
            QuotaWindow(
                key="monthly",
                label="월간 사용량",
                used_percent=self._parse_percent(monthly_usage),
                used_value=self._parse_decimal(monthly_usage.get("used")),
                limit_value=self._parse_decimal(monthly_usage.get("limit")),
                remaining_value=self._parse_decimal(monthly_usage.get("remaining")),
                unit=monthly_usage.get("unit"),
            ),
        ]

        balances = []
        if management_key:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        "https://openrouter.ai/api/v1/credits",
                        headers={
                            "Authorization": f"Bearer {management_key}",
                            "Accept": "application/json",
                        },
                    )
                    response.raise_for_status()
                    credit_payload = response.json()
                    credit_data = credit_payload.get("data", {})
                    balances.append(
                        CreditBalance(
                            currency=credit_data.get("currency", "USD"),
                            total=self._parse_decimal(credit_data.get("total")),
                            remaining=self._parse_decimal(credit_data.get("remaining")),
                            used=self._parse_decimal(credit_data.get("used")),
                            granted=self._parse_decimal(credit_data.get("granted")),
                            topped_up=self._parse_decimal(credit_data.get("topped_up")),
                        )
                    )
            except httpx.HTTPError:
                balances = []

        return self._build_snapshot(
            status=ProviderStatus.OK,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            quota_windows=quota_windows,
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
        quota_windows: list[QuotaWindow] | None = None,
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
            quota_windows=quota_windows or [],
            balances=balances or [],
            message=message,
            error_code=error_code,
        )

    @staticmethod
    def _parse_percent(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

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
