from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector

CLAUDE_CONFIG_DIR = Path.home() / ".claude"
CLAUDE_CODE_DIR = Path.home() / "AppData" / "Roaming" / "Claude" / "claude-code"
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
