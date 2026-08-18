from __future__ import annotations

import json

from ai_usage_monitor.collectors import codex_app_server as codex_module
from ai_usage_monitor.collectors.codex_app_server import CodexAppServerCollector
from ai_usage_monitor.domain.enums import ProviderStatus


def test_codex_collector_reports_weekly_only_and_ignores_spark_limit(tmp_path, monkeypatch) -> None:
    """The secondary (spark model) window is deliberately not surfaced."""
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
                            "resets_at": 1786162620,
                        },
                        "secondary": {
                            "used_percent": 33,
                            "window_minutes": 300,
                            "resets_at": 1785948000,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_module.CodexAppServerCollector, "CODEX_SESSIONS_DIR", tmp_path)

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert [(quota.key, quota.used_percent) for quota in snapshot.quota_windows] == [
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

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert len(snapshot.quota_windows) == 1
    assert snapshot.quota_windows[0].key == "weekly"


def test_codex_collector_reports_missing_fixed_sessions_path(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing"
    monkeypatch.setattr(codex_module.CodexAppServerCollector, "CODEX_SESSIONS_DIR", missing_path)

    snapshot = CodexAppServerCollector().collect()

    assert snapshot.status == ProviderStatus.UNAVAILABLE
    assert snapshot.error_code == "CODEX_SESSIONS_PATH_MISSING"
