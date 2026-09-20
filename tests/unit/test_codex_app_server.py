from __future__ import annotations

import json
from datetime import datetime, timezone

from ai_usage_monitor.collectors import codex_app_server as codex_module
from ai_usage_monitor.collectors.codex_app_server import CodexAppServerCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import QuotaWindow


def test_codex_collector_reports_five_hour_and_weekly_windows(tmp_path, monkeypatch) -> None:
    session_path = tmp_path / "2026" / "08" / "05" / "session.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-05T04:36:56.512Z",
                "payload": {
                    "rate_limits": {
                        "primary": {
                            "used_percent": 69,
                            "window_minutes": 10080,
                            "resets_at": 1890000000,
                        },
                        "secondary": {
                            "used_percent": 33,
                            "window_minutes": 300,
                            "resets_at": 1890000000,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_module.CodexAppServerCollector, "CODEX_SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(
        CodexAppServerCollector,
        "_read_live_rate_limits",
        classmethod(lambda cls: []),
    )

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert [(quota.key, quota.used_percent) for quota in snapshot.quota_windows] == [
        ("five_hour", 33.0),
        ("weekly", 69.0),
    ]
    assert all(quota.resets_at is not None for quota in snapshot.quota_windows)


def test_codex_collector_keeps_weekly_when_five_hour_is_missing(tmp_path, monkeypatch) -> None:
    session_path = tmp_path / "session.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "payload": {
                    "rate_limits": {
                        "primary": {
                            "used_percent": 69,
                            "window_minutes": 10080,
                        },
                        "secondary": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_module.CodexAppServerCollector, "CODEX_SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(
        CodexAppServerCollector,
        "_read_live_rate_limits",
        classmethod(lambda cls: []),
    )

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.quota_windows) == 1
    assert snapshot.quota_windows[0].key == "weekly"


def test_codex_collector_reports_missing_fixed_sessions_path(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing"
    monkeypatch.setattr(codex_module.CodexAppServerCollector, "CODEX_SESSIONS_DIR", missing_path)
    monkeypatch.setattr(
        CodexAppServerCollector,
        "_codex_exe_candidates",
        classmethod(lambda cls: []),
    )
    monkeypatch.setattr(
        CodexAppServerCollector,
        "_read_live_rate_limits",
        classmethod(lambda cls: []),
    )

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.UNAVAILABLE
    assert snapshot.error_code == "CODEX_SESSIONS_PATH_MISSING"


def test_codex_collector_prefers_live_app_server_rate_limits(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing"
    live_quota = QuotaWindow(
        key="weekly",
        label="주간 사용량",
        used_percent=9,
        unit="percent",
        window_minutes=10080,
        resets_at=datetime(2030, 9, 26, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(CodexAppServerCollector, "CODEX_SESSIONS_DIR", missing_path)
    monkeypatch.setattr(
        CodexAppServerCollector,
        "_read_live_rate_limits",
        classmethod(lambda cls: [live_quota]),
    )

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert [(quota.key, quota.used_percent) for quota in snapshot.quota_windows] == [
        ("weekly", 9)
    ]


def test_codex_parser_accepts_official_app_server_field_names() -> None:
    quotas = CodexAppServerCollector._parse_rate_limits(
        {
            "primary": {
                "usedPercent": 9,
                "windowDurationMins": 10080,
                "resetsAt": 1790410945,
            },
            "secondary": None,
        }
    )

    assert [(quota.key, quota.used_percent) for quota in quotas] == [("weekly", 9.0)]
    assert quotas[0].resets_at == datetime.fromtimestamp(1790410945, tz=timezone.utc)


def test_codex_session_fallback_ignores_expired_rate_limit(tmp_path, monkeypatch) -> None:
    session_path = tmp_path / "old-session.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "payload": {
                    "rate_limits": {
                        "primary": {
                            "used_percent": 59,
                            "window_minutes": 10080,
                            "resets_at": 1789241137,
                        },
                        "secondary": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(CodexAppServerCollector, "CODEX_SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(
        CodexAppServerCollector,
        "_read_live_rate_limits",
        classmethod(lambda cls: []),
    )

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.ERROR
    assert snapshot.error_code == "CODEX_USAGE_PARSE_ERROR"
