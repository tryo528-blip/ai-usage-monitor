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

        quota_windows = []
        limit = self._parse_decimal(data.get("limit"))
        limit_remaining = self._parse_decimal(data.get("limit_remaining"))
        metadata = {
            "usage": data.get("usage"),
            "usage_daily": data.get("usage_daily"),
            "usage_weekly": data.get("usage_weekly"),
            "usage_monthly": data.get("usage_monthly"),
            "limit_reset": data.get("limit_reset"),
            "expires_at": data.get("expires_at"),
        }

        if limit is not None and limit_remaining is not None:
            used_value = limit - limit_remaining
            used_percent = None
            if limit > 0:
                used_percent = float((used_value / limit) * Decimal("100"))
            quota_key = self._quota_key_from_reset(data.get("limit_reset"))
            quota_windows.append(
                QuotaWindow(
                    key=quota_key,
                    label=f"{self._label_from_reset(data.get('limit_reset'))} 사용량",
                    used_percent=used_percent,
                    used_value=used_value,
                    limit_value=limit,
                    remaining_value=limit_remaining,
                    unit="USD",
                    resets_at=None,
                )
            )

        balances = []
        credit_error = None
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
                    total_credits = self._parse_decimal(credit_data.get("total_credits"))
                    total_usage = self._parse_decimal(credit_data.get("total_usage"))
                    remaining = None
                    if total_credits is not None and total_usage is not None:
                        remaining = max(total_credits - total_usage, Decimal("0"))
                    balances.append(
                        CreditBalance(
                            currency="USD",
                            total=total_credits,
                            used=total_usage,
                            remaining=remaining,
                        )
                    )
            except httpx.HTTPError as exc:
                credit_error = str(exc)
            except ValueError:
                credit_error = "INVALID_RESPONSE"

        if credit_error is not None:
            metadata["credit_lookup_error"] = credit_error

        return self._build_snapshot(
            status=ProviderStatus.OK,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            quota_windows=quota_windows,
            balances=balances,
            metadata=metadata,
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
        metadata: dict | None = None,
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
            metadata=metadata or {},
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

    @staticmethod
    def _quota_key_from_reset(value: object) -> str:
        if isinstance(value, str):
            lowered = value.lower()
            if "weekly" in lowered:
                return "weekly"
            if "monthly" in lowered:
                return "monthly"
        return "daily"

    @staticmethod
    def _label_from_reset(value: object) -> str:
        if isinstance(value, str):
            lowered = value.lower()
            if "weekly" in lowered:
                return "주간"
            if "monthly" in lowered:
                return "월간"
        return "일간"
