from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ai_usage_monitor.collectors import antyg_bridge
from ai_usage_monitor.collectors.antyg_bridge import AntigravityCollector
from ai_usage_monitor.domain.enums import ProviderStatus, SourceType

STRUCTURED_USAGE = json.dumps(
    {
        "response": {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "bucketId": "gemini-weekly",
                            "displayName": "Weekly Limit",
                            "window": "weekly",
                            "remainingFraction": 0.72,
                            "resetTime": "2026-08-30T12:00:00Z",
                        },
                        {
                            "bucketId": "gemini-5h",
                            "displayName": "Five Hour Limit",
                            "window": "5h",
                            "remainingFraction": 0.84,
                            "resetTime": "2026-08-28T15:00:00Z",
                        },
                    ],
                },
                {
                    "displayName": "Claude and GPT models",
                    "buckets": [
                        {
                            "bucketId": "other-weekly",
                            "displayName": "Weekly Limit",
                            "window": "weekly",
                            "remainingFraction": 0.99,
                        }
                    ],
                },
            ]
        },
        "aiCredits": {"remaining": 42},
    }
)


def test_antigravity_parser_keeps_gemini_group_and_converts_remaining_fraction() -> None:
    quotas = AntigravityCollector._parse_usage(
        STRUCTURED_USAGE,
        now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
    )

    assert [quota.key for quota in quotas] == ["five_hour", "weekly"]
    assert quotas[0].used_percent == pytest.approx(16.0)
    assert quotas[1].used_percent == pytest.approx(28.0)
    assert quotas[0].resets_at == datetime(2026, 8, 28, 15, tzinfo=timezone.utc)


def test_antigravity_parser_accepts_rendered_usage_text() -> None:
    output = """
    Models & Quota
    Gemini Models
    Five Hour Limit    83.5% remaining    refreshes in 2h
    Weekly Limit       71% remaining
    Claude and GPT models
    Weekly Limit       99% remaining
    """

    quotas = AntigravityCollector._parse_usage(
        output,
        now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
    )

    assert [(quota.key, quota.used_percent) for quota in quotas] == [
        ("five_hour", 16.5),
        ("weekly", 29.0),
    ]
    assert quotas[0].resets_at == datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)


def test_antigravity_parser_reads_tagged_remaining_and_credits() -> None:
    payload = {
        "groups": [
            {
                "name": "Gemini Models",
                "buckets": [
                    {
                        "id": "gemini-5h",
                        "window": "5-hour",
                        "remaining": {"case": "remainingFraction", "value": 0.5},
                    }
                ],
            }
        ],
        "credits": {"available": "1,234"},
    }

    quotas = AntigravityCollector._parse_usage(
        json.dumps(payload),
        now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
    )
    balances = AntigravityCollector._parse_credits(json.dumps(payload))

    assert [(quota.key, quota.used_percent) for quota in quotas] == [("five_hour", 50.0)]
    assert balances[0].currency == "AI credits"
    assert balances[0].remaining == Decimal("1234.0")


def test_antigravity_parser_prefers_bucket_window_over_group_description() -> None:
    payload = {
        "command": {
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "description": ("Models share a weekly limit and a 5-hour limit."),
                        "buckets": [
                            {
                                "id": "gemini-weekly",
                                "name": "Weekly Limit Remaining",
                                "window": "weekly",
                                "remaining_fraction": 0.95,
                                "reset_time": "2026-09-25T05:24:40Z",
                            },
                            {
                                "id": "gemini-5h",
                                "name": "Five Hour Limit Remaining",
                                "window": "5h",
                                "remaining_fraction": 1,
                                "reset_time": "2026-09-20T13:26:38Z",
                            },
                        ],
                    }
                ]
            }
        }
    }

    quotas = AntigravityCollector._parse_usage(
        json.dumps(payload),
        now=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )

    assert [quota.key for quota in quotas] == ["five_hour", "weekly"]
    assert quotas[0].used_percent == pytest.approx(0.0)
    assert quotas[1].used_percent == pytest.approx(5.0)
    assert quotas[0].resets_at == datetime(2026, 9, 20, 13, 26, 38, tzinfo=timezone.utc)
    assert quotas[1].resets_at == datetime(2026, 9, 25, 5, 24, 40, tzinfo=timezone.utc)


def test_antigravity_usage_runs_read_only_cli_in_print_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        AntigravityCollector,
        "_agy_exe_candidates",
        classmethod(lambda cls: ["agy-test.exe"]),
    )
    monkeypatch.setattr(antyg_bridge.Path, "home", staticmethod(lambda: tmp_path))
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=STRUCTURED_USAGE.encode(), stderr=b"")

    monkeypatch.setattr(antyg_bridge.subprocess, "run", fake_run)

    output = AntigravityCollector._run_usage()

    assert "Gemini Models" in output
    assert captured["args"] == ["agy-test.exe", "-p", "/usage", "--output-format", "json"]
    assert captured["stdin"] == antyg_bridge.subprocess.DEVNULL
    assert captured["timeout"] == antyg_bridge.ANTYG_TIMEOUT_SECONDS
    assert captured["cwd"] == str(tmp_path)
    assert captured["env"]["AGY_CLI_HIDE_ACCOUNT_INFO"] == "1"


def test_antigravity_collector_reports_missing_cli(monkeypatch) -> None:
    monkeypatch.setattr(AntigravityCollector, "_agy_exe_candidates", classmethod(lambda cls: []))

    snapshot = AntigravityCollector().collect()

    assert snapshot.status == ProviderStatus.UNAVAILABLE
    assert snapshot.source_type == SourceType.LOCAL_BRIDGE
    assert snapshot.error_code == "ANTYG_CLI_NOT_FOUND"


def test_antigravity_collector_reports_auth_required(monkeypatch) -> None:
    monkeypatch.setattr(
        AntigravityCollector,
        "_agy_exe_candidates",
        classmethod(lambda cls: ["agy-test.exe"]),
    )
    monkeypatch.setattr(
        AntigravityCollector,
        "_run_usage",
        classmethod(lambda cls: "Welcome to the Antigravity CLI. You are currently not signed in."),
    )

    snapshot = AntigravityCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "ANTYG_AUTH_REQUIRED"


def test_antigravity_collector_returns_snapshot_from_structured_output(monkeypatch) -> None:
    monkeypatch.setattr(
        AntigravityCollector,
        "_agy_exe_candidates",
        classmethod(lambda cls: ["agy-test.exe"]),
    )
    monkeypatch.setattr(
        AntigravityCollector,
        "_run_usage",
        classmethod(lambda cls: STRUCTURED_USAGE),
    )

    snapshot = AntigravityCollector().collect()

    assert snapshot.status == ProviderStatus.OK
    assert snapshot.provider_id == "antyg"
    assert snapshot.provider_name == "Google Antigravity (Gemini)"
    assert [quota.key for quota in snapshot.quota_windows] == ["five_hour", "weekly"]
    assert snapshot.balances[0].remaining == Decimal("42.0")


def test_antigravity_collector_does_not_request_separate_optional_credits(monkeypatch) -> None:
    usage_calls: list[str] = []
    usage_without_credits = json.dumps(
        {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "displayName": "Weekly Limit",
                            "window": "weekly",
                            "remainingFraction": 0.9,
                        }
                    ],
                }
            ]
        }
    )

    monkeypatch.setattr(
        AntigravityCollector,
        "_run_usage",
        classmethod(lambda cls: usage_calls.append("usage") or usage_without_credits),
    )

    snapshot = AntigravityCollector().collect()

    assert usage_calls == ["usage"]
    assert snapshot.status == ProviderStatus.OK
    assert snapshot.balances == []
