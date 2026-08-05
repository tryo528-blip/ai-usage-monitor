from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector

GROK_CONFIG_DIR = Path(r"C:\Users\sswce\.grok")
GROK_AUTH_PATH = GROK_CONFIG_DIR / "auth.json"
GROK_LOG_PATH = GROK_CONFIG_DIR / "logs" / "unified.jsonl"
GROK_TIMEOUT_SECONDS = 10.0

GROK_USAGE_ENDPOINTS = (
    "https://grok.com/rest/subscriptions",
    "https://grok.com/rest/user",
    "https://grok.com/rest/billing/usage",
    "https://grok.com/rest/usage",
    "https://cli-chat-proxy.grok.com/v1/billing",
)


class GrokCollector(Collector):
    provider_id = "grok"
    provider_name = "Grok"

    def is_configured(self) -> bool:
        return GROK_AUTH_PATH.is_file()

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        bearer_token = self._load_bearer_token()
        if not bearer_token:
            return self._snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message=f"Grok 로그인 정보를 찾을 수 없습니다: {GROK_AUTH_PATH}",
                collected_at=now,
                error_code="GROK_AUTH_NOT_CONFIGURED",
            )

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/?_s=usage",
        }
        try:
            with httpx.Client(timeout=GROK_TIMEOUT_SECONDS) as client:
                for endpoint in GROK_USAGE_ENDPOINTS:
                    response = client.get(
                        endpoint,
                        headers={
                            **headers,
                            **(
                                {"x-xai-token-auth": "xai-grok-cli"}
                                if endpoint.startswith("https://cli-chat-proxy.grok.com/")
                                else {}
                            ),
                        },
                    )
                    if response.status_code in {401, 403}:
                        return self._snapshot(
                            status=ProviderStatus.AUTH_REQUIRED,
                            message="Grok 인증이 만료되었습니다. Grok에 다시 로그인해 주세요.",
                            collected_at=now,
                            error_code="AUTH_FAILED",
                        )
                    if response.status_code == 429:
                        return self._snapshot(
                            status=ProviderStatus.WARNING,
                            message="Grok 사용량 조회가 제한되었습니다.",
                            collected_at=now,
                            error_code="RATE_LIMITED",
                        )
                    if response.status_code != 200 or not response.content:
                        continue
                    try:
                        payload = response.json()
                    except ValueError:
                        continue
                    quota = self._parse_quota(payload)
                    if quota is not None:
                        return self._snapshot(
                            status=ProviderStatus.OK,
                            message="정상 조회",
                            collected_at=now,
                            last_success_at=now,
                            quota_windows=[quota],
                        )
        except httpx.TimeoutException:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Grok 응답 시간이 초과되었습니다.",
                collected_at=now,
                error_code="NETWORK_TIMEOUT",
            )
        except httpx.HTTPError:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Grok 연결 오류입니다.",
                collected_at=now,
                error_code="NETWORK_ERROR",
            )

        return self._snapshot(
            status=ProviderStatus.UNAVAILABLE,
            message="Grok 주간한도 정보를 확인할 수 없습니다.",
            collected_at=now,
            error_code="USAGE_DATA_UNAVAILABLE",
        )

    @staticmethod
    def _load_bearer_token() -> str | None:
        if not GROK_AUTH_PATH.is_file():
            return None
        try:
            raw = GROK_AUTH_PATH.read_text(encoding="utf-8")
        except OSError:
            return None
        # The CLI auth file has occasionally been emitted with invalid JSON. Keep this
        # narrow extractor so a harmless profile field cannot prevent usage collection.
        match = re.search(r'"key"\s*:\s*"([^"\r\n]+)"', raw)
        return match.group(1).strip() if match else None

    @classmethod
    def _parse_quota(cls, payload: object) -> QuotaWindow | None:
        if not isinstance(payload, dict):
            return None
        used_percent = cls._find_number(
            payload,
            {
                "usedPercent",
                "usagePercent",
                "credit_usage_percent",
                "percentUsed",
                "used_percent",
                "usage_percent",
                "percent",
            },
        )
        limit_value = cls._find_number(payload, {"monthlyLimit", "limit", "totalLimit"})
        used_value = cls._find_number(payload, {"used", "totalUsed", "includedUsed"})
        if used_percent is None and limit_value and used_value is not None:
            used_percent = used_value / limit_value * 100
        if used_percent is None:
            return None
        reset_value = cls._find_value(
            payload,
            {"resetsAt", "resetAt", "reset_at", "billingPeriodEnd", "periodEnd", "nextReset"},
        )
        return QuotaWindow(
            key="weekly",
            label="주간 사용량",
            used_percent=max(Decimal("0"), min(Decimal("100"), used_percent)),
            used_value=used_value,
            limit_value=limit_value,
            unit="percent" if used_value is None else None,
            window_minutes=7 * 24 * 60,
            resets_at=cls._parse_datetime(reset_value),
        )

    @classmethod
    def _find_number(cls, value: object, keys: set[str]) -> Decimal | None:
        found = cls._find_value(value, keys)
        if isinstance(found, dict):
            found = found.get("val")
        if isinstance(found, (int, float, str, Decimal)) and not isinstance(found, bool):
            try:
                return Decimal(str(found))
            except Exception:
                return None
        return None

    @classmethod
    def _find_value(cls, value: object, keys: set[str]) -> object | None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in keys:
                    return child
            for child in value.values():
                found = cls._find_value(child, keys)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_value(child, keys)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _snapshot(
        self,
        *,
        status: ProviderStatus,
        message: str,
        collected_at: datetime,
        error_code: str | None = None,
        last_success_at: datetime | None = None,
        quota_windows: list[QuotaWindow] | None = None,
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
            message=message,
            error_code=error_code,
        )
