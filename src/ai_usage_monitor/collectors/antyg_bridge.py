from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Mapping

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import CreditBalance, QuotaWindow, UsageSnapshot

from .base import Collector

ANTYG_TIMEOUT_SECONDS = 30
ANTYG_COMMAND = "/usage"
ANTYG_CLI_HIDE_ACCOUNT_INFO = "1"

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
_AUTH_REQUIRED_PATTERN = re.compile(
    r"(?:not\s+signed\s+in|sign(?:ed|ing)?\s+in|log\s*in|authenticate|authentication|"
    r"account\s+(?:is\s+)?ineligible|eligibility)",
    re.IGNORECASE,
)
_TEXT_PERCENT_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
_RELATIVE_RESET_PATTERN = re.compile(
    r"(?:refresh|reset)(?:es|s)?\s+in\s+"
    r"(?:(?P<days>\d+(?:\.\d+)?)\s*d(?:ays?)?\s*)?"
    r"(?:(?P<hours>\d+(?:\.\d+)?)\s*h(?:ours?)?\s*)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)\s*m(?:in(?:utes?)?)?\s*)?",
    re.IGNORECASE,
)
_CREDIT_TEXT_PATTERN = re.compile(
    r"(?:AI\s+Credits?|G1\s+Credits?|Active\s+Balance)\s*[:=-]\s*"
    r"(?P<value>[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


class AntigravityAuthRequired(RuntimeError):
    """The local Antigravity CLI has no usable signed-in session."""


class AntigravityCollector(Collector):
    """Read Gemini quota from the signed-in Google Antigravity CLI.

    Antigravity exposes quota through its own CLI/TUI rather than a Gemini API
    balance endpoint. The collector uses the read-only ``/usage`` command in
    print mode, accepts both structured and rendered responses, and never
    passes a user prompt to the CLI.
    """

    provider_id = "antyg"
    provider_name = "Google Antigravity (Gemini)"

    def is_configured(self) -> bool:
        return bool(self._agy_exe_candidates())

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        try:
            output = self._run_usage()
        except FileNotFoundError as exc:
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message=f"Antigravity CLI 없음: {exc}",
                collected_at=now,
                error_code="ANTYG_CLI_NOT_FOUND",
            )
        except AntigravityAuthRequired:
            return self._snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message="Antigravity에 먼저 로그인해 주세요.",
                collected_at=now,
                error_code="ANTYG_AUTH_REQUIRED",
            )
        except (TimeoutError, subprocess.TimeoutExpired):
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Antigravity 사용량 조회 시간 초과",
                collected_at=now,
                error_code="ANTYG_USAGE_TIMEOUT",
            )
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message=f"Antigravity 조회 실패: {exc}",
                collected_at=now,
                error_code="ANTYG_USAGE_ERROR",
            )

        if self._looks_auth_required(output):
            return self._snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message="Antigravity에 먼저 로그인해 주세요.",
                collected_at=now,
                error_code="ANTYG_AUTH_REQUIRED",
            )

        quota_windows = self._parse_usage(output, now=now)
        balances = self._parse_credits(output)
        if not quota_windows:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Antigravity quota 응답을 해석할 수 없습니다.",
                collected_at=now,
                error_code="ANTYG_USAGE_PARSE_ERROR",
                balances=balances,
            )

        return self._snapshot(
            status=ProviderStatus.OK,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            quota_windows=quota_windows,
            balances=balances,
        )

    @classmethod
    def _agy_exe_candidates(cls) -> list[str]:
        candidates: list[str] = []

        def add(value: str | None) -> None:
            if value and value not in candidates:
                candidates.append(value)

        for name in ("agy.exe", "agy"):
            add(shutil.which(name))

        for extra in (
            Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "agy" / "agy.exe",
            Path.home() / ".agy" / "bin" / "agy.exe",
            Path.home() / ".local" / "bin" / "agy",
        ):
            if extra.is_file():
                add(str(extra))

        return candidates

    @classmethod
    def _run_usage(cls) -> str:
        return cls._run_cli_command(ANTYG_COMMAND)

    @classmethod
    def _run_cli_command(cls, command_name: str) -> str:
        candidates = cls._agy_exe_candidates()
        if not candidates:
            raise FileNotFoundError(cls._lookup_diagnostics())

        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        environment = os.environ.copy()
        # Avoid putting the Google account email or plan header into the
        # monitor's captured output/logging path.
        environment["AGY_CLI_HIDE_ACCOUNT_INFO"] = ANTYG_CLI_HIDE_ACCOUNT_INFO
        errors: list[str] = []

        for command in candidates:
            try:
                completed = subprocess.run(
                    [command, "-p", command_name, "--output-format", "json"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=ANTYG_TIMEOUT_SECONDS,
                    check=False,
                    creationflags=creation_flags,
                    env=environment,
                    cwd=str(Path.home()),
                )
            except OSError as exc:
                errors.append(f"{Path(command).name}: {exc}")
                continue

            stdout = cls._decode_output(completed.stdout)
            stderr = cls._decode_output(completed.stderr)
            combined = "\n".join(part for part in (stdout, stderr) if part).strip()
            if cls._looks_auth_required(combined):
                raise AntigravityAuthRequired()
            if completed.returncode != 0:
                detail = cls._single_line_detail(combined)
                errors.append(f"{Path(command).name}: rc={completed.returncode} {detail}")
                continue
            if combined:
                return combined
            errors.append(f"{Path(command).name}: 빈 응답")

        raise RuntimeError("; ".join(errors) or "알 수 없는 실패")

    @staticmethod
    def _decode_output(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    @staticmethod
    def _single_line_detail(value: str) -> str:
        clean = AntigravityCollector._strip_ansi(value)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:180] or "응답 없음"

    @staticmethod
    def _looks_auth_required(value: str) -> bool:
        return bool(_AUTH_REQUIRED_PATTERN.search(AntigravityCollector._strip_ansi(value)))

    @staticmethod
    def _lookup_diagnostics() -> str:
        return f"home={Path.home()} | which={[shutil.which(name) for name in ('agy.exe', 'agy')]}"

    @classmethod
    def _parse_usage(cls, output: str | None, *, now: datetime) -> list[QuotaWindow]:
        text = cls._strip_ansi(output or "")
        candidates: list[tuple[int, QuotaWindow]] = []
        text_parts = [text]

        for payload in cls._json_payloads(text):
            candidates.extend(cls._structured_quota_candidates(payload, now=now))
            text_parts.extend(cls._embedded_text(payload))

        selected: dict[str, tuple[int, QuotaWindow]] = {}
        for priority, quota in candidates:
            current = selected.get(quota.key)
            if current is None or priority > current[0]:
                selected[quota.key] = (priority, quota)

        if not selected:
            for quota in cls._text_quota_candidates("\n".join(text_parts), now=now):
                selected.setdefault(quota.key, (0, quota))

        order = {"five_hour": 0, "weekly": 1}
        return [
            item[1]
            for item in sorted(selected.values(), key=lambda item: order.get(item[1].key, 99))
        ]

    @classmethod
    def _json_payloads(cls, text: str) -> list[object]:
        payloads: list[object] = []
        stripped = text.strip()
        if not stripped:
            return payloads

        try:
            payloads.append(json.loads(stripped))
        except json.JSONDecodeError:
            for line in stripped.splitlines():
                try:
                    payloads.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return payloads

    @classmethod
    def _embedded_text(cls, payload: object) -> list[str]:
        texts: list[str] = []
        for value in cls._walk_values(payload):
            if isinstance(value, str) and ("%" in value or "quota" in value.lower()):
                texts.append(value)
        return texts

    @classmethod
    def _structured_quota_candidates(
        cls, payload: object, *, now: datetime
    ) -> list[tuple[int, QuotaWindow]]:
        candidates: list[tuple[int, QuotaWindow]] = []
        for mapping, context in cls._walk_mappings(payload):
            metric = cls._quota_metric(mapping)
            if metric is None:
                continue
            key = cls._quota_key(mapping, context)
            if key is None:
                continue
            priority = 2 if "gemini" in " ".join(context).lower() else 1
            label = "5시간 사용량" if key == "five_hour" else "주간 사용량"
            candidates.append(
                (
                    priority,
                    QuotaWindow(
                        key=key,
                        label=label,
                        used_percent=metric,
                        unit="percent",
                        window_minutes=300 if key == "five_hour" else 10080,
                        resets_at=cls._mapping_reset_time(mapping, now=now),
                    ),
                )
            )
        return candidates

    @classmethod
    def _text_quota_candidates(cls, text: str, *, now: datetime) -> list[QuotaWindow]:
        quotas: dict[str, QuotaWindow] = {}
        active_group = ""
        context_lines: list[str] = []
        for raw_line in text.splitlines():
            line = cls._strip_ansi(raw_line).strip()
            if not line:
                continue
            lower = line.lower()
            if "gemini" in lower:
                active_group = "gemini"
            elif "claude" in lower or re.search(r"\bgpt\b", lower):
                active_group = "other"
            context_lines.append(line)
            context_lines = context_lines[-3:]

            match = _TEXT_PERCENT_PATTERN.search(line)
            if not match or active_group == "other":
                continue
            key = cls._quota_key_from_text(line) or cls._quota_key_from_text(
                " ".join(context_lines)
            )
            if key is None:
                continue
            value = float(match.group("value"))
            is_used = bool(re.search(r"\b(?:used|consumed)\b", lower))
            if not is_used and not re.search(r"\b(?:remaining|left|available|limit)\b", lower):
                continue
            used_percent = value if is_used else 100.0 - value
            reset_at = cls._text_reset_time(line, now=now)
            quotas[key] = QuotaWindow(
                key=key,
                label="5시간 사용량" if key == "five_hour" else "주간 사용량",
                used_percent=max(0.0, min(100.0, used_percent)),
                unit="percent",
                window_minutes=300 if key == "five_hour" else 10080,
                resets_at=reset_at,
            )
        return list(quotas.values())

    @classmethod
    def _parse_credits(cls, output: str | None) -> list[CreditBalance]:
        text = cls._strip_ansi(output or "")
        values: list[Decimal] = []
        for payload in cls._json_payloads(text):
            for mapping, _ in cls._walk_mappings(payload):
                for key, value in mapping.items():
                    normalized = cls._normalize_key(key)
                    if normalized in {
                        "aicredits",
                        "g1credits",
                        "remainingcredits",
                        "activebalance",
                    }:
                        number = cls._decimal_value(value)
                        if number is not None:
                            values.append(number)
                        elif isinstance(value, Mapping):
                            for child_key in ("remaining", "available", "balance", "value"):
                                number = cls._decimal_value(value.get(child_key))
                                if number is not None:
                                    values.append(number)
                                    break
                    elif normalized in {"credits", "creditbalance"} and isinstance(value, Mapping):
                        for child_key in ("remaining", "available", "balance", "value"):
                            number = cls._decimal_value(value.get(child_key))
                            if number is not None:
                                values.append(number)
                                break
        for match in _CREDIT_TEXT_PATTERN.finditer(text):
            try:
                values.append(Decimal(match.group("value").replace(",", "")))
            except InvalidOperation:
                continue
        if not values:
            return []
        return [CreditBalance(currency="AI credits", remaining=values[0])]

    @classmethod
    def _quota_metric(cls, mapping: Mapping[str, Any]) -> float | None:
        for key, value in mapping.items():
            normalized = cls._normalize_key(key)
            if normalized in {"remainingfraction", "remainingratio"}:
                number = cls._number_value(value)
                if number is not None and 0 <= number <= 1:
                    return (1.0 - number) * 100.0
            if normalized in {"usedfraction", "usedratio"}:
                number = cls._number_value(value)
                if number is not None and 0 <= number <= 1:
                    return number * 100.0
            if normalized in {"remainingpercent", "remainingpercentage"}:
                number = cls._number_value(value)
                if number is not None and 0 <= number <= 100:
                    return 100.0 - number
            if normalized in {"usedpercent", "usedpercentage", "percentused"}:
                number = cls._number_value(value)
                if number is not None and 0 <= number <= 100:
                    return number
            if normalized == "remaining" and isinstance(value, Mapping):
                case = cls._normalize_key(value.get("case") or value.get("type"))
                number = cls._number_value(value.get("value"))
                if number is None:
                    continue
                if case in {"remainingfraction", "remainingratio"} and 0 <= number <= 1:
                    return (1.0 - number) * 100.0
                if case in {"remainingpercent", "remainingpercentage"} and 0 <= number <= 100:
                    return 100.0 - number
        return None

    @classmethod
    def _quota_key(cls, mapping: Mapping[str, Any], context: tuple[str, ...]) -> str | None:
        # Prefer the bucket's own identifiers over inherited group context.
        # Current agy output includes a group description mentioning both the
        # weekly and five-hour limits. Combining that description with a
        # weekly bucket made the five-hour matcher win simply because it is
        # checked first.
        direct_values = [
            str(value) for value in mapping.values() if isinstance(value, (str, int, float))
        ]
        direct_key = cls._quota_key_from_text(" ".join(direct_values))
        if direct_key is not None:
            return direct_key
        return cls._quota_key_from_text(" ".join(context))

    @staticmethod
    def _quota_key_from_text(value: str) -> str | None:
        normalized = re.sub(r"[_-]", " ", value.lower())
        if re.search(r"(?:five\s*hour|5\s*hour|5\s*h|session)", normalized):
            return "five_hour"
        if re.search(r"(?:weekly|week|7\s*day)", normalized):
            return "weekly"
        return None

    @classmethod
    def _mapping_reset_time(cls, mapping: Mapping[str, Any], *, now: datetime) -> datetime | None:
        for key, value in mapping.items():
            if cls._normalize_key(key) in {
                "resettime",
                "resetat",
                "resetsat",
                "refreshat",
            }:
                parsed = cls._parse_datetime(value, now=now)
                if parsed is not None:
                    return parsed
        return None

    @classmethod
    def _text_reset_time(cls, line: str, *, now: datetime) -> datetime | None:
        match = _RELATIVE_RESET_PATTERN.search(line)
        if not match:
            return None
        delta = timedelta(
            days=float(match.group("days") or 0),
            hours=float(match.group("hours") or 0),
            minutes=float(match.group("minutes") or 0),
        )
        return now + delta if delta.total_seconds() else None

    @staticmethod
    def _parse_datetime(value: object, *, now: datetime) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        elif isinstance(value, str) and value.strip():
            raw = value.strip()
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _walk_mappings(
        cls, value: object, context: tuple[str, ...] = ()
    ) -> Iterator[tuple[Mapping[str, Any], tuple[str, ...]]]:
        if isinstance(value, Mapping):
            labels = tuple(
                str(child)
                for key, child in value.items()
                if cls._normalize_key(key)
                in {"displayname", "label", "name", "window", "bucketid", "description"}
                and isinstance(child, (str, int, float))
            )
            next_context = context + labels
            yield value, next_context
            for key, child in value.items():
                yield from cls._walk_mappings(child, next_context + (str(key),))
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_mappings(child, context)

    @classmethod
    def _walk_values(cls, value: object) -> Iterator[object]:
        yield value
        if isinstance(value, Mapping):
            for child in value.values():
                yield from cls._walk_values(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_values(child)

    @staticmethod
    def _strip_ansi(value: str) -> str:
        return _ANSI_ESCAPE_PATTERN.sub("", value)

    @staticmethod
    def _normalize_key(value: object) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    @staticmethod
    def _number_value(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float, Decimal)):
            return float(value)
        if isinstance(value, str):
            raw = value.strip().replace(",", "").rstrip("%")
            try:
                return float(raw)
            except ValueError:
                return None
        return None

    @classmethod
    def _decimal_value(cls, value: object) -> Decimal | None:
        number = cls._number_value(value)
        if number is None:
            return None
        try:
            return Decimal(str(number))
        except InvalidOperation:
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
        balances: list[CreditBalance] | None = None,
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
            balances=balances or [],
            message=message,
            error_code=error_code,
        )
