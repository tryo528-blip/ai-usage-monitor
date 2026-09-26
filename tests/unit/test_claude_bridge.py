from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ai_usage_monitor.collectors import claude_bridge
from ai_usage_monitor.collectors.claude_bridge import ClaudeBridgeCollector
from ai_usage_monitor.domain.enums import ProviderStatus

USAGE_OUTPUT = """
Current session: 33% used · resets Aug 5, 3:20pm (Asia/Seoul)
Current week (all models): 29% used · resets Aug 9, 10pm (Asia/Seoul)
"""


def test_claude_usage_parses_percentages_and_reset_times(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ClaudeBridgeCollector, "_run_usage", staticmethod(lambda: USAGE_OUTPUT))
    collector = ClaudeBridgeCollector()

    snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.OK
    assert [(quota.key, quota.used_percent) for quota in snapshot.quota_windows] == [
        ("five_hour", 33.0),
        ("weekly", 29.0),
    ]
    assert snapshot.quota_windows[0].resets_at is not None
    assert snapshot.quota_windows[0].resets_at.tzinfo is not None
    assert snapshot.quota_windows[0].resets_at.utcoffset() == timedelta(hours=9)


def test_claude_usage_parses_terminal_decorated_lines() -> None:
    decorated = "\x1b[2K│ " + USAGE_OUTPUT.replace("Current", "\x1b[36mCurrent")

    quotas = ClaudeBridgeCollector._parse_usage(
        decorated,
        now=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 33.0),
        ("weekly", 29.0),
    ]


def test_claude_usage_parses_fable_weekly_bucket() -> None:
    output = USAGE_OUTPUT + (
        "Current week (Fable only): 41% used · resets Aug 9, 10pm (Asia/Seoul)\n"
    )

    quotas = ClaudeBridgeCollector._parse_usage(
        output,
        now=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 33.0),
        ("weekly", 29.0),
        ("weekly_fable", 41.0),
    ]
    assert quotas[2].label == "Fable 주간 사용량"
    assert quotas[2].resets_at is not None


def _stub_candidates(monkeypatch, *paths: str) -> None:
    monkeypatch.setattr(
        ClaudeBridgeCollector,
        "_claude_exe_candidates",
        classmethod(lambda cls: list(paths)),
    )


def test_claude_usage_runs_cli_in_print_mode_and_reads_json_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    _stub_candidates(monkeypatch, r"C:\fake\claude.exe")
    calls: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({"result": USAGE_OUTPUT}).encode()
        stderr = b""

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["env"] = kwargs.get("env")
        calls["timeout"] = kwargs.get("timeout")
        return Completed()

    monkeypatch.setattr(claude_bridge.subprocess, "run", fake_run)

    output = ClaudeBridgeCollector._run_usage()

    assert "Current week" in output
    assert calls["args"] == [r"C:\fake\claude.exe", "-p", "/usage", "--output-format", "json"]
    assert calls["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path)
    assert calls["timeout"] == claude_bridge.USAGE_TIMEOUT_SECONDS


def test_claude_usage_falls_through_to_next_candidate_when_one_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    _stub_candidates(monkeypatch, r"C:\broken\claude.exe", r"C:\good\claude.exe")
    attempted: list[str] = []

    class Completed:
        returncode = 0
        stdout = json.dumps({"result": USAGE_OUTPUT}).encode()
        stderr = b""

    def fake_run(args, **kwargs):
        attempted.append(args[0])
        if args[0] == r"C:\broken\claude.exe":
            raise OSError("[WinError 3] not found")
        return Completed()

    monkeypatch.setattr(claude_bridge.subprocess, "run", fake_run)

    output = ClaudeBridgeCollector._run_usage()

    assert "Current week" in output
    assert attempted == [r"C:\broken\claude.exe", r"C:\good\claude.exe"]


def test_claude_exe_candidates_include_msix_package_location(monkeypatch, tmp_path) -> None:
    """Claude Code ships as an MSIX package, which redirects %APPDATA%.

    Processes outside the package cannot see the unpackaged path, so the
    packaged LocalCache location must be probed explicitly.
    """
    unpackaged = tmp_path / "AppData" / "Roaming" / "Claude" / "claude-code"
    packaged = (
        tmp_path
        / "AppData"
        / "Local"
        / "Packages"
        / "Claude_pzs8sxrjxfjjc"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude-code"
        / "2.1.229"
    )
    packaged.mkdir(parents=True)
    (packaged / "claude.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr(claude_bridge, "CLAUDE_CODE_DIR", unpackaged)
    monkeypatch.setattr(claude_bridge.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(claude_bridge.shutil, "which", lambda name: None)

    candidates = ClaudeBridgeCollector._claude_exe_candidates()

    assert str(packaged / "claude.exe") in candidates


def test_claude_exe_candidates_prefer_newest_version_numerically(monkeypatch, tmp_path) -> None:
    root = tmp_path / "claude-code"
    for version in ("2.1.30", "2.1.229"):
        version_dir = root / version
        version_dir.mkdir(parents=True)
        (version_dir / "claude.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr(claude_bridge, "CLAUDE_CODE_DIR", root)
    monkeypatch.setattr(claude_bridge.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(claude_bridge.shutil, "which", lambda name: None)

    candidates = ClaudeBridgeCollector._claude_exe_candidates()

    assert candidates[0] == str(root / "2.1.229" / "claude.exe")


def test_claude_usage_reports_missing_fixed_config_path(monkeypatch, tmp_path) -> None:
    missing_path = tmp_path / "claude"
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", missing_path)
    collector = ClaudeBridgeCollector()

    snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.UNAVAILABLE
    assert snapshot.error_code == "CLAUDE_CONFIG_PATH_MISSING"
    assert str(missing_path) in (snapshot.message or "")


def test_claude_usage_reports_unparseable_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ClaudeBridgeCollector, "_run_usage", staticmethod(lambda: "no usage"))

    snapshot = ClaudeBridgeCollector().collect()

    assert snapshot.status == ProviderStatus.ERROR
    assert snapshot.error_code == "CLAUDE_USAGE_PARSE_ERROR"


def test_claude_usage_handles_empty_cli_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ClaudeBridgeCollector, "_run_usage", staticmethod(lambda: None))

    snapshot = ClaudeBridgeCollector().collect()

    assert snapshot.status == ProviderStatus.ERROR
    assert snapshot.error_code == "CLAUDE_USAGE_PARSE_ERROR"


def test_usage_api_json_maps_session_week_and_any_fable_bucket() -> None:
    data = {
        "five_hour": {"utilization": 30.0, "resets_at": "2026-09-26T05:20:00+00:00"},
        "seven_day": {"utilization": 17, "resets_at": "2026-09-27T13:00:00Z"},
        "seven_day_opus": None,
        "seven_day_fable": {"utilization": 0, "resets_at": "2026-09-27T13:00:00Z"},
        "extra_usage": {"is_enabled": False},
    }

    quotas = ClaudeBridgeCollector._parse_usage_json(data)

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 30.0),
        ("weekly", 17.0),
        ("weekly_fable", 0.0),
    ]
    assert quotas[0].resets_at == datetime(2026, 9, 26, 5, 20, tzinfo=timezone.utc)
    assert quotas[2].label == "Fable 주간 사용량"


def test_usage_api_json_finds_nested_fable_bucket() -> None:
    data = {
        "five_hour": {"utilization": 5},
        "seven_day": {"utilization": 9},
        "model_limits": {"Fable": {"utilization": 41, "resets_at": None}},
    }

    quotas = ClaudeBridgeCollector._parse_usage_json(data)

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 5.0),
        ("weekly", 9.0),
        ("weekly_fable", 41.0),
    ]


def test_collect_prefers_usage_api_over_cli(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        ClaudeBridgeCollector,
        "fetch_usage_json",
        classmethod(
            lambda cls, now: {
                "five_hour": {"utilization": 30},
                "seven_day": {"utilization": 17},
                "seven_day_fable": {"utilization": 0},
            }
        ),
    )

    def fail_cli() -> str:
        raise AssertionError("CLI must not run when the API answered")

    monkeypatch.setattr(ClaudeBridgeCollector, "_run_usage", staticmethod(fail_cli))

    snapshot = ClaudeBridgeCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert [quota.key for quota in snapshot.quota_windows] == [
        "five_hour",
        "weekly",
        "weekly_fable",
    ]


def test_collect_falls_back_to_cli_without_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        ClaudeBridgeCollector, "fetch_usage_json", classmethod(lambda cls, now: None)
    )
    monkeypatch.setattr(ClaudeBridgeCollector, "_run_usage", staticmethod(lambda: USAGE_OUTPUT))

    snapshot = ClaudeBridgeCollector().collect()

    assert [quota.key for quota in snapshot.quota_windows] == ["five_hour", "weekly"]


def test_access_token_expiry_handling(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    credentials = tmp_path / ".credentials.json"

    def token_with(expires_at: int) -> str | None:
        credentials.write_text(
            '{"claudeAiOauth": {"accessToken": "tok", "expiresAt": %d}}' % expires_at,
            encoding="utf-8",
        )
        return ClaudeBridgeCollector._read_access_token(now=now)

    now_ms = int(now.timestamp() * 1000)
    assert token_with(now_ms + 600_000) == "tok"
    assert token_with(0) == "tok"  # 0 means no known expiry
    assert token_with(now_ms + 30_000) is None  # inside the safety margin
    assert token_with(now_ms - 60_000) is None


def test_usage_api_http_failure_falls_back_to_cli(monkeypatch, tmp_path) -> None:
    import httpx

    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    (tmp_path / ".credentials.json").write_text(
        '{"claudeAiOauth": {"accessToken": "tok", "expiresAt": 0}}', encoding="utf-8"
    )

    def unauthorized(*_args, **_kwargs):
        request = httpx.Request("GET", claude_bridge.USAGE_API_URL)
        return httpx.Response(401, request=request)

    monkeypatch.setattr(claude_bridge.httpx, "get", unauthorized)
    monkeypatch.setattr(ClaudeBridgeCollector, "_run_usage", staticmethod(lambda: USAGE_OUTPUT))

    snapshot = ClaudeBridgeCollector().collect()

    assert [(quota.key, quota.used_percent) for quota in snapshot.quota_windows] == [
        ("five_hour", 33.0),
        ("weekly", 29.0),
    ]


def test_cli_parser_never_borrows_the_next_lines_percentage() -> None:
    quotas = ClaudeBridgeCollector._parse_usage(
        "Current session: no usage yet\nCurrent week (all models): 29% used\n",
        now=datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc),
    )
    assert [(quota.key, quota.used_percent) for quota in quotas] == [("weekly", 29.0)]

    korean = ClaudeBridgeCollector._parse_usage(
        "현재 세션 사용량 없음\n이번 주\n29% 사용됨\n",
        now=datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc),
    )
    assert [(quota.key, quota.used_percent) for quota in korean] == [("weekly", 29.0)]


def test_cli_parser_accepts_bare_week_but_not_model_specific_week() -> None:
    now = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
    assert [
        (q.key, q.used_percent)
        for q in ClaudeBridgeCollector._parse_usage("Current week: 45% used", now=now)
    ] == [("weekly", 45.0)]
    assert [
        (q.key, q.used_percent)
        for q in ClaudeBridgeCollector._parse_usage(
            "Current week (Sonnet only): 3% used\nCurrent week (all models): 20% used", now=now
        )
    ] == [("weekly", 20.0)]


def test_usage_api_matches_nested_buckets_and_prefers_weekly_fable() -> None:
    data = {
        "limits": {
            "five_hour": {"utilization": 12},
            "seven_day": {"utilization": 34},
        },
        "fable": {
            "five_hour": {"utilization": 90},
            "seven_day": {"utilization": 56},
        },
    }

    quotas = ClaudeBridgeCollector._parse_usage_json(data)

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 12.0),
        ("weekly", 34.0),
        ("weekly_fable", 56.0),
    ]


def test_claude_raw_dump_masks_identifiers() -> None:
    from ai_usage_monitor.cli import redact_identifiers

    masked = redact_identifiers(
        {
            "five_hour": {"utilization": 3, "resets_at": "2026-09-26T05:00:00Z"},
            "organization_uuid": "org-123",
            "extra": [{"account_email": "me@example.com"}],
        }
    )

    assert masked["five_hour"] == {"utilization": 3, "resets_at": "2026-09-26T05:00:00Z"}
    assert masked["organization_uuid"] == "***"
    assert masked["extra"] == [{"account_email": "***"}]


def test_cli_parser_reads_korean_usage_text() -> None:
    output = (
        "현재 세션\n오후 2:20에 재설정\n30% 사용됨\n"
        "이번 주\n재설정: (일요일) 오후 10:00\n17% 사용됨\n"
        "이번 주 Fable\n별도 주간 한도 대상: Fable · 재설정: (일요일) 오후 10:00\n0% 사용됨\n"
    )

    quotas = ClaudeBridgeCollector._parse_usage(
        output,
        now=datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc),
    )

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 30.0),
        ("weekly", 17.0),
        ("weekly_fable", 0.0),
    ]


def test_cost_summary_from_cli_reports_token_problem(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        ClaudeBridgeCollector, "fetch_usage_json", classmethod(lambda cls, now: None)
    )
    monkeypatch.setattr(
        ClaudeBridgeCollector,
        "_run_usage",
        staticmethod(lambda: "Total cost:            $0.0000\nUsage: 0 input, 0 output"),
    )

    snapshot = ClaudeBridgeCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "CLAUDE_TOKEN_UNAVAILABLE"
    assert "토큰" in snapshot.message
