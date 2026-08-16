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


def test_claude_usage_falls_through_to_next_candidate_when_one_fails(
    monkeypatch, tmp_path
) -> None:
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
