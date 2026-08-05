from __future__ import annotations

from decimal import Decimal

import respx

from ai_usage_monitor.collectors import grok as grok_module
from ai_usage_monitor.collectors.grok import GrokCollector
from ai_usage_monitor.domain.enums import ProviderStatus


def _auth_file(tmp_path, monkeypatch) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text('{"key": "test-bearer-token"}', encoding="utf-8")
    monkeypatch.setattr(grok_module, "GROK_AUTH_PATH", auth_path)


def test_grok_collector_uses_fixed_auth_path_and_parses_weekly_usage(tmp_path, monkeypatch) -> None:
    _auth_file(tmp_path, monkeypatch)
    collector = GrokCollector()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://grok.com/rest/subscriptions").respond(
            200,
            json={"usage": {"usedPercent": 35}, "resetsAt": "2026-08-06T12:00:00Z"},
        )
        snapshot = collector.collect()

    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-bearer-token"
    assert snapshot.status == ProviderStatus.OK
    assert snapshot.quota_windows[0].used_percent == 35
    assert snapshot.quota_windows[0].resets_at is not None


def test_grok_collector_parses_cli_limit_shape() -> None:
    quota = GrokCollector._parse_quota(
        {
            "monthlyLimit": {"val": "100"},
            "usage": {"totalUsed": {"val": "12.5"}},
            "billingCycle": {"billingPeriodEnd": "2026-08-06T12:00:00Z"},
        }
    )

    assert quota is not None
    assert quota.used_percent == Decimal("12.5")
    assert quota.used_value == Decimal("12.5")
    assert quota.limit_value == Decimal("100")


def test_grok_collector_requires_fixed_auth_file(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing-auth.json"
    monkeypatch.setattr(grok_module, "GROK_AUTH_PATH", missing_path)

    snapshot = GrokCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "GROK_AUTH_NOT_CONFIGURED"


def test_grok_collector_surfaces_expired_auth(tmp_path, monkeypatch) -> None:
    _auth_file(tmp_path, monkeypatch)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://grok.com/rest/subscriptions").respond(401)
        snapshot = GrokCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
