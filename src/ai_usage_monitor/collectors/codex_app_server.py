from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector


class CodexAppServerCollector(Collector):
    provider_id = "codex"
    provider_name = "Codex"
    CODEX_SESSIONS_DIR = Path(r"C:\Users\sswce\.codex\sessions")

    def is_configured(self) -> bool:
        return self.CODEX_SESSIONS_DIR.is_dir()

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        if not self.is_configured():
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message=f"Codex 세션 경로를 찾을 수 없습니다: {self.CODEX_SESSIONS_DIR}",
                collected_at=now,
                error_code="CODEX_SESSIONS_PATH_MISSING",
            )

        quota_windows = self._read_latest_rate_limits()
        if quota_windows:
            return self._snapshot(
                status=ProviderStatus.OK,
                message="정상 조회",
                collected_at=now,
                last_success_at=now,
                quota_windows=quota_windows,
            )

        return self._snapshot(
            status=ProviderStatus.ERROR,
            message="Codex 세션 로그에서 사용량을 찾을 수 없습니다.",
            collected_at=now,
            error_code="CODEX_USAGE_PARSE_ERROR",
        )

    @classmethod
    def _read_latest_rate_limits(cls) -> list[QuotaWindow]:
        files = sorted(
            cls.CODEX_SESSIONS_DIR.glob("**/*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files:
            latest: dict[str, object] | None = None
            try:
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        payload = record.get("payload") if isinstance(record, dict) else None
                        rate_limits = (
                            payload.get("rate_limits") if isinstance(payload, dict) else None
                        )
                        if isinstance(rate_limits, dict):
                            latest = rate_limits
            except OSError:
                continue

            if latest is not None:
                return cls._parse_rate_limits(latest)
        return []

    @staticmethod
    def _parse_rate_limits(rate_limits: dict[str, object]) -> list[QuotaWindow]:
        quotas: list[QuotaWindow] = []
        for value in (rate_limits.get("primary"), rate_limits.get("secondary")):
            if not isinstance(value, dict):
                continue
            window_minutes = value.get("window_minutes")
            used_percent = value.get("used_percent")
            if not isinstance(window_minutes, int) or not isinstance(used_percent, (int, float)):
                continue
            if window_minutes == 300:
                key, label = "five_hour", "5시간 사용량"
            elif window_minutes == 10080:
                key, label = "weekly", "주간 사용량"
            else:
                continue
            reset_value = value.get("resets_at")
            reset_at = (
                datetime.fromtimestamp(reset_value, tz=timezone.utc)
                if isinstance(reset_value, (int, float))
                else None
            )
            quotas.append(
                QuotaWindow(
                    key=key,
                    label=label,
                    used_percent=float(used_percent),
                    unit="percent",
                    window_minutes=window_minutes,
                    resets_at=reset_at,
                )
            )
        return quotas

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
            source_type=SourceType.LOCAL_RPC,
            status=status,
            collected_at=collected_at,
            last_success_at=last_success_at,
            stale_after_seconds=900,
            quota_windows=quota_windows or [],
            message=message,
            error_code=error_code,
        )
