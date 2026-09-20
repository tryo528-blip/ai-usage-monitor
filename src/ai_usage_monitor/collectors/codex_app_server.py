from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector


class CodexAppServerCollector(Collector):
    provider_id = "codex"
    provider_name = "Codex"
    CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
    APP_SERVER_TIMEOUT_SECONDS = 10

    def is_configured(self) -> bool:
        return bool(self._codex_exe_candidates()) or self.CODEX_SESSIONS_DIR.is_dir()

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        try:
            quota_windows = self._read_live_rate_limits()
        except (FileNotFoundError, OSError, RuntimeError, subprocess.SubprocessError):
            quota_windows = []

        quota_windows = self._unexpired_quotas(quota_windows, now=now)
        if quota_windows:
            return self._snapshot(
                status=ProviderStatus.OK,
                message="정상 조회",
                collected_at=now,
                last_success_at=now,
                quota_windows=quota_windows,
            )

        if not self.is_configured():
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message="Codex CLI와 세션 경로를 찾을 수 없습니다.",
                collected_at=now,
                error_code="CODEX_SESSIONS_PATH_MISSING",
            )

        quota_windows = self._read_latest_rate_limits(now=now)
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
            message="Codex 실시간 조회와 유효한 세션 로그에서 사용량을 찾을 수 없습니다.",
            collected_at=now,
            error_code="CODEX_USAGE_PARSE_ERROR",
        )

    @classmethod
    def _codex_exe_candidates(cls) -> list[str]:
        candidates: list[str] = []

        def add(value: str | None) -> None:
            if value and value not in candidates:
                candidates.append(value)

        for name in ("codex.exe", "codex"):
            add(shutil.which(name))

        for extra in (
            Path.home() / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin"
            / "codex.exe",
            Path.home() / ".local" / "bin" / "codex",
        ):
            if extra.is_file():
                add(str(extra))
        return candidates

    @classmethod
    def _read_live_rate_limits(cls) -> list[QuotaWindow]:
        candidates = cls._codex_exe_candidates()
        if not candidates:
            raise FileNotFoundError("Codex CLI not found")

        errors: list[str] = []
        for command in candidates:
            try:
                response = cls._query_app_server(command)
                rate_limits = cls._extract_live_rate_limits(response)
                if rate_limits is None:
                    raise RuntimeError("rate limit response missing")
                return cls._parse_rate_limits(rate_limits)
            except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
                errors.append(f"{Path(command).name}: {exc}")
        raise RuntimeError("; ".join(errors) or "Codex app-server query failed")

    @classmethod
    def _query_app_server(cls, command: str) -> dict[str, Any]:
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(
            [command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
            cwd=str(Path.home()),
        )
        messages: queue.Queue[dict[str, Any]] = queue.Queue()

        def read_messages() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    messages.put(message)

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        try:
            cls._send_app_server_message(
                process,
                {
                    "method": "initialize",
                    "id": 0,
                    "params": {
                        "clientInfo": {
                            "name": "ai_usage_monitor",
                            "title": "AI Usage Monitor",
                            "version": "0.1.0",
                        }
                    },
                },
            )
            cls._wait_for_response(messages, request_id=0)
            cls._send_app_server_message(process, {"method": "initialized", "params": {}})
            cls._send_app_server_message(
                process,
                {"method": "account/rateLimits/read", "id": 1},
            )
            return cls._wait_for_response(messages, request_id=1)
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    @staticmethod
    def _send_app_server_message(
        process: subprocess.Popen[str], message: dict[str, Any]
    ) -> None:
        if process.stdin is None:
            raise RuntimeError("Codex app-server stdin unavailable")
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    @classmethod
    def _wait_for_response(
        cls, messages: queue.Queue[dict[str, Any]], *, request_id: int
    ) -> dict[str, Any]:
        deadline = time.monotonic() + cls.APP_SERVER_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Codex app-server request {request_id} timed out")
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"Codex app-server request {request_id} timed out"
                ) from exc
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"Codex app-server request {request_id} failed")
            return message

    @staticmethod
    def _extract_live_rate_limits(response: dict[str, Any]) -> dict[str, object] | None:
        result = response.get("result")
        if not isinstance(result, dict):
            return None
        by_limit = result.get("rateLimitsByLimitId")
        if isinstance(by_limit, dict):
            codex_limit = by_limit.get("codex")
            if isinstance(codex_limit, dict):
                return codex_limit
        rate_limits = result.get("rateLimits")
        return rate_limits if isinstance(rate_limits, dict) else None

    @classmethod
    def _read_latest_rate_limits(cls, *, now: datetime) -> list[QuotaWindow]:
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
                quotas = cls._unexpired_quotas(cls._parse_rate_limits(latest), now=now)
                if quotas:
                    return quotas
        return []

    @staticmethod
    def _unexpired_quotas(
        quota_windows: list[QuotaWindow], *, now: datetime
    ) -> list[QuotaWindow]:
        return [
            quota
            for quota in quota_windows
            if quota.resets_at is None or quota.resets_at > now
        ]

    @staticmethod
    def _parse_rate_limits(rate_limits: dict[str, object]) -> list[QuotaWindow]:
        parsed: dict[str, QuotaWindow] = {}
        window_specs = {
            300: ("five_hour", "5시간 사용량"),
            10080: ("weekly", "주간 사용량"),
        }
        for slot in ("primary", "secondary"):
            value = rate_limits.get(slot)
            if not isinstance(value, dict):
                continue
            window_minutes = value.get("window_minutes", value.get("windowDurationMins"))
            used_percent = value.get("used_percent", value.get("usedPercent"))
            if not isinstance(window_minutes, int) or not isinstance(used_percent, (int, float)):
                continue
            spec = window_specs.get(window_minutes)
            if spec is None:
                continue
            key, label = spec
            reset_value = value.get("resets_at", value.get("resetsAt"))
            reset_at = (
                datetime.fromtimestamp(reset_value, tz=timezone.utc)
                if isinstance(reset_value, (int, float))
                else None
            )
            parsed[key] = QuotaWindow(
                key=key,
                label=label,
                used_percent=float(used_percent),
                unit="percent",
                window_minutes=window_minutes,
                resets_at=reset_at,
            )
        return [parsed[key] for key in ("five_hour", "weekly") if key in parsed]

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
