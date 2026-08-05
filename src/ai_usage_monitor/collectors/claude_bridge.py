from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QProcess, QProcessEnvironment

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector

CLAUDE_CONFIG_DIR = Path(r"C:\Users\sswce\.claude")
USAGE_TIMEOUT_SECONDS = 30
USAGE_LINE_PATTERNS = {
    "five_hour": re.compile(r"Current session:\s*(?P<percent>\d+(?:\.\d+)?)%", re.IGNORECASE),
    "weekly": re.compile(
        r"Current week \(all models\):\s*(?P<percent>\d+(?:\.\d+)?)%",
        re.IGNORECASE,
    ),
}
RESET_PATTERN = re.compile(r"resets\s+(?P<reset>.+?)\s+\((?P<zone>[^)]+)\)", re.IGNORECASE)


class ClaudeBridgeCollector(Collector):
    provider_id = "claude"
    provider_name = "Claude"

    def is_configured(self) -> bool:
        return CLAUDE_CONFIG_DIR.is_dir()

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        if not self.is_configured():
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message=f"Claude 설정 경로를 찾을 수 없습니다: {CLAUDE_CONFIG_DIR}",
                collected_at=now,
                error_code="CLAUDE_CONFIG_PATH_MISSING",
            )

        try:
            usage_output = self._run_usage()
        except FileNotFoundError:
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message="Claude CLI를 찾을 수 없습니다.",
                collected_at=now,
                error_code="CLAUDE_CLI_NOT_FOUND",
            )
        except TimeoutError:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Claude 사용량 조회 시간이 초과되었습니다.",
                collected_at=now,
                error_code="CLAUDE_USAGE_TIMEOUT",
            )
        except RuntimeError as exc:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message=f"Claude 사용량을 읽을 수 없습니다: {exc}",
                collected_at=now,
                error_code="CLAUDE_USAGE_ERROR",
            )

        quota_windows = self._parse_usage(usage_output, now=now)
        if not quota_windows:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Claude /usage 결과에서 사용량을 찾을 수 없습니다.",
                collected_at=now,
                error_code="CLAUDE_USAGE_PARSE_ERROR",
            )

        return self._snapshot(
            status=ProviderStatus.OK,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            quota_windows=quota_windows,
        )

    @staticmethod
    def _run_usage() -> str:
        command = "claude.cmd" if os.name == "nt" else "claude"
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("CLAUDE_CONFIG_DIR", str(CLAUDE_CONFIG_DIR))
        process = QProcess()
        process.setProgram(command)
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.start()
        if not process.waitForStarted(5000):
            raise FileNotFoundError(command)
        process.write(b"/usage\n/exit\n")
        process.closeWriteChannel()
        if not process.waitForFinished(USAGE_TIMEOUT_SECONDS * 1000):
            process.kill()
            process.waitForFinished(1000)
            raise TimeoutError(f"timeout after {USAGE_TIMEOUT_SECONDS} seconds")
        if process.exitCode() != 0:
            raise RuntimeError(f"exit code {process.exitCode()}")
        return bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")

    @classmethod
    def _parse_usage(cls, output: str | None, *, now: datetime) -> list[QuotaWindow]:
        quotas: list[QuotaWindow] = []
        normalized = re.sub(r"\s+", " ", cls._strip_terminal_control(output or "")).strip()
        for key, pattern in USAGE_LINE_PATTERNS.items():
            match = pattern.search(normalized)
            if not match:
                continue
            percent = float(match.group("percent"))
            reset_match = RESET_PATTERN.search(normalized[match.end() : match.end() + 180])
            reset_at = None
            if reset_match:
                reset_at = cls._parse_reset(
                    reset_match.group("reset"), reset_match.group("zone"), now=now
                )
            label = "5시간 사용량" if key == "five_hour" else "주간 사용량"
            window_minutes = 5 * 60 if key == "five_hour" else 7 * 24 * 60
            quotas.append(
                QuotaWindow(
                    key=key,
                    label=label,
                    used_percent=percent,
                    unit="percent",
                    window_minutes=window_minutes,
                    resets_at=reset_at,
                )
            )
        return quotas

    @staticmethod
    def _strip_terminal_control(value: str) -> str:
        value = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", value)
        value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
        return value.replace("\r", "")

    @staticmethod
    def _parse_reset(value: str, zone_name: str, *, now: datetime) -> datetime | None:
        if zone_name.strip().lower() in {"asia/seoul", "kst"}:
            zone = timezone(timedelta(hours=9), name="KST")
        else:
            try:
                zone = ZoneInfo(zone_name)
            except KeyError:
                zone = timezone.utc
        parsed = None
        for fmt in ("%b %d, %I:%M%p", "%b %d, %I%p"):
            try:
                parsed = datetime.strptime(f"{now.year} {value}", f"%Y {fmt}")
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        parsed = parsed.replace(tzinfo=zone)
        if parsed.astimezone(timezone.utc) < now:
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed

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
            source_type=SourceType.LOCAL_BRIDGE,
            status=status,
            collected_at=collected_at,
            last_success_at=last_success_at,
            stale_after_seconds=900,
            quota_windows=quota_windows or [],
            message=message,
            error_code=error_code,
        )
