from __future__ import annotations

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


def test_claude_usage_runs_hidden_cli_with_fixed_config_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_bridge, "CLAUDE_CONFIG_DIR", tmp_path)
    calls = []

    class FakeProcess:
        class ProcessChannelMode:
            MergedChannels = object()

        def setProgram(self, command):
            calls.append(("program", command))

        def setProcessEnvironment(self, environment):
            calls.append(("environment", environment))

        def setProcessChannelMode(self, mode):
            calls.append(("channel_mode", mode))

        def start(self):
            calls.append(("start",))

        def waitForStarted(self, timeout):
            calls.append(("wait_started", timeout))
            return True

        def write(self, data):
            calls.append(("write", data))

        def closeWriteChannel(self):
            calls.append(("close_write",))

        def waitForFinished(self, timeout):
            calls.append(("wait_finished", timeout))
            return True

        def exitCode(self):
            return 0

        def readAllStandardOutput(self):
            return USAGE_OUTPUT.encode()

    monkeypatch.setattr(claude_bridge, "QProcess", FakeProcess)

    output = ClaudeBridgeCollector._run_usage()

    assert "Current week" in output
    assert ("program", "claude.cmd") in calls
    assert ("write", b"/usage\n/exit\n") in calls
    assert ("wait_finished", claude_bridge.USAGE_TIMEOUT_SECONDS * 1000) in calls


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
