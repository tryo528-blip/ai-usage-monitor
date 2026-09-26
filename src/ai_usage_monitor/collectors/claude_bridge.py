from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector

CLAUDE_CONFIG_DIR = Path.home() / ".claude"
CLAUDE_CODE_DIR = Path.home() / "AppData" / "Roaming" / "Claude" / "claude-code"
USAGE_TIMEOUT_SECONDS = 30
_PERCENT = r"(?P<percent>\d+(?:\.\d+)?)\s*%"
# English CLI output ("Current week (Fable only): 0% used") and the Korean UI
# wording ("이번 주 Fable ... 0% 사용됨"). The label-to-percent gap may not
# cross another percent sign, so one line never borrows the next line's value.
USAGE_LINE_PATTERNS = {
    "five_hour": re.compile(
        r"(?:Current session|현재 세션)[^%]{0,80}?" + _PERCENT,
        re.IGNORECASE,
    ),
    "weekly": re.compile(
        r"(?:Current week \(all models\)|이번 주(?!\s*\(?\s*fable))[^%]{0,80}?" + _PERCENT,
        re.IGNORECASE,
    ),
    "weekly_fable": re.compile(
        r"(?:Current week|이번 주)\s*\(?[^%:]{0,20}?fable[^%]{0,80}?" + _PERCENT,
        re.IGNORECASE,
    ),
}
USAGE_LABELS = {
    "five_hour": "5시간 사용량",
    "weekly": "주간 사용량",
    "weekly_fable": "Fable 주간 사용량",
}
USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_API_TIMEOUT_SECONDS = 10
# Top-level buckets of the usage API that the settings page renders as
# "현재 세션" and "이번 주". Any bucket whose path mentions "fable" is the
# separate Fable weekly limit, whatever the exact key is.
API_BUCKET_KEYS = {"five_hour": "five_hour", "seven_day": "weekly"}
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

        api_quotas = self._fetch_usage_api(now=now)
        if api_quotas:
            return self._snapshot(
                status=ProviderStatus.OK,
                message="정상 조회",
                collected_at=now,
                last_success_at=now,
                quota_windows=api_quotas,
            )

        try:
            usage_output = self._run_usage()
        except FileNotFoundError as exc:
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message=f"CLI 없음: {exc}",
                collected_at=now,
                error_code="CLAUDE_CLI_NOT_FOUND",
            )
        except (TimeoutError, subprocess.TimeoutExpired):
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="시간 초과",
                collected_at=now,
                error_code="CLAUDE_USAGE_TIMEOUT",
            )
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message=f"조회 실패: {exc}",
                collected_at=now,
                error_code="CLAUDE_USAGE_ERROR",
            )

        quota_windows = self._parse_usage(usage_output, now=now)
        if not quota_windows:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="파싱 실패",
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

    # -- usage API (what claude.ai settings shows) -------------------------------------

    @staticmethod
    def _read_access_token(*, now: datetime) -> str | None:
        """The Claude Code OAuth token, or None when missing or expired.

        The token never leaves this process except as the bearer header to
        Anthropic's own API, exactly as Claude Code itself sends it.
        """

        try:
            data = json.loads((CLAUDE_CONFIG_DIR / ".credentials.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        if not isinstance(oauth, dict):
            return None
        token = oauth.get("accessToken")
        expires_at = oauth.get("expiresAt")
        if isinstance(expires_at, (int, float)) and expires_at / 1000 <= now.timestamp():
            # Expired: the CLI path below refreshes it as a side effect.
            return None
        return token if isinstance(token, str) and token else None

    @classmethod
    def fetch_usage_json(cls, *, now: datetime) -> Any | None:
        token = cls._read_access_token(now=now)
        if token is None:
            return None
        try:
            response = httpx.get(
                USAGE_API_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
                timeout=USAGE_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None

    @classmethod
    def _fetch_usage_api(cls, *, now: datetime) -> list[QuotaWindow]:
        data = cls.fetch_usage_json(now=now)
        return cls._parse_usage_json(data) if data is not None else []

    @staticmethod
    def _iter_buckets(
        data: Any, path: tuple[str, ...] = ()
    ) -> Iterator[tuple[tuple[str, ...], dict]]:
        """Yield every dict carrying a numeric ``utilization``, with its key path."""

        if not isinstance(data, dict):
            return
        if isinstance(data.get("utilization"), (int, float)):
            yield path, data
        for key, value in data.items():
            if isinstance(value, dict):
                yield from ClaudeBridgeCollector._iter_buckets(value, (*path, str(key)))

    @classmethod
    def _parse_usage_json(cls, data: Any) -> list[QuotaWindow]:
        found: dict[str, dict] = {}
        for path, bucket in cls._iter_buckets(data):
            joined = "/".join(path).lower()
            if "fable" in joined:
                key = "weekly_fable"
            elif len(path) == 1 and path[0] in API_BUCKET_KEYS:
                key = API_BUCKET_KEYS[path[0]]
            else:
                continue
            found.setdefault(key, bucket)

        quotas = []
        for key in ("five_hour", "weekly", "weekly_fable"):
            bucket = found.get(key)
            if bucket is None:
                continue
            percent = max(0.0, min(100.0, float(bucket["utilization"])))
            quotas.append(
                QuotaWindow(
                    key=key,
                    label=USAGE_LABELS[key],
                    used_percent=percent,
                    unit="percent",
                    window_minutes=5 * 60 if key == "five_hour" else 7 * 24 * 60,
                    resets_at=cls._parse_iso(bucket.get("resets_at")),
                )
            )
        return quotas

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    # -- CLI fallback -----------------------------------------------------------------

    @staticmethod
    def _version_sort_key(path: Path) -> tuple:
        parts = []
        for chunk in path.name.split("."):
            parts.append(int(chunk) if chunk.isdigit() else -1)
        return tuple(parts)

    @staticmethod
    def _claude_code_roots() -> list[Path]:
        """Directories holding per-version Claude Code installs.

        Claude Code ships as an MSIX package, which redirects %APPDATA% into the
        package's LocalCache. That redirected copy is invisible to processes
        running outside the package, so the packaged location must be probed
        explicitly rather than relying on %APPDATA%.
        """
        roots = [CLAUDE_CODE_DIR]
        packages = Path.home() / "AppData" / "Local" / "Packages"
        try:
            for package in sorted(packages.glob("Claude_*")):
                roots.append(package / "LocalCache" / "Roaming" / "Claude" / "claude-code")
        except OSError:
            pass
        return roots

    @classmethod
    def _claude_exe_candidates(cls) -> list[str]:
        """Every plausible claude executable, best first. Never raises."""
        candidates: list[str] = []

        def add(value: str | None) -> None:
            if value and value not in candidates:
                candidates.append(value)

        for name in ("claude.cmd", "claude.exe", "claude"):
            add(shutil.which(name))

        for root in cls._claude_code_roots():
            try:
                version_dirs = sorted(
                    (p for p in root.iterdir() if p.is_dir()),
                    key=cls._version_sort_key,
                    reverse=True,
                )
            except OSError:
                continue
            for version_dir in version_dirs:
                for exe_name in ("claude.exe", "claude.cmd", "claude"):
                    exe = version_dir / exe_name
                    if exe.is_file():
                        add(str(exe))

        for extra in (
            Path.home() / "AppData" / "Local" / "Programs" / "claude" / "claude.exe",
            Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
            Path.home() / ".claude" / "bin" / "claude.exe",
            Path.home() / ".local" / "bin" / "claude.exe",
        ):
            if extra.is_file():
                add(str(extra))

        return candidates

    @staticmethod
    def _lookup_diagnostics() -> str:
        """Why did the search come up empty? Captured into the snapshot message."""
        bits = [f"home={Path.home()}", f"APPDATA={os.environ.get('APPDATA')}"]
        for root in ClaudeBridgeCollector._claude_code_roots():
            try:
                entries = [p.name for p in root.iterdir()]
                bits.append(f"{root}={entries}")
            except OSError as exc:
                bits.append(f"{root}!{type(exc).__name__}")
        bits.append(f"which={[shutil.which(n) for n in ('claude.cmd', 'claude.exe', 'claude')]}")
        return " | ".join(bits)

    @classmethod
    def _run_usage(cls) -> str:
        candidates = cls._claude_exe_candidates()
        if not candidates:
            raise FileNotFoundError(cls._lookup_diagnostics())

        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(CLAUDE_CONFIG_DIR)
        # PyInstaller injects these into its own env; leaking them into a child
        # trips the bootloader's parent-process check if the child is frozen too.
        leaked_vars = (
            "_PYI_APPLICATION_HOME_DIR",
            "_PYI_ARCHIVE_FILE",
            "_PYI_PARENT_PROCESS_LEVEL",
            "_MEIPASS2",
        )
        for leaked in leaked_vars:
            env.pop(leaked, None)

        errors: list[str] = []
        for command in candidates:
            try:
                completed = subprocess.run(
                    [command, "-p", "/usage", "--output-format", "json"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=USAGE_TIMEOUT_SECONDS,
                    check=False,
                    creationflags=creation_flags,
                    env=env,
                    cwd=str(Path.home()),
                )
            except subprocess.TimeoutExpired:
                raise
            except OSError as exc:
                errors.append(f"{Path(command).name}: {exc}")
                continue

            if completed.returncode != 0:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                errors.append(f"{Path(command).name}: rc={completed.returncode} {detail[:120]}")
                continue

            raw = completed.stdout.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                result = data.get("result")
            except (json.JSONDecodeError, AttributeError):
                result = None
            return result if isinstance(result, str) and result else raw

        raise RuntimeError("; ".join(errors) or "알 수 없는 실패")

    @classmethod
    def _parse_usage(cls, output: str | None, *, now: datetime) -> list[QuotaWindow]:
        quotas: list[QuotaWindow] = []
        normalized = re.sub(r"\s+", " ", (output or "")).strip()
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
            label = USAGE_LABELS[key]
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
