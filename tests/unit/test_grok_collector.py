from __future__ import annotations

from datetime import datetime, timezone

import respx

from ai_usage_monitor.collectors import grok as grok_module
from ai_usage_monitor.collectors.grok import (
    GROK_CREDITS_CONFIG_ENDPOINT,
    GROK_GRPC_WEB_REQUEST,
    GrokCollector,
)
from ai_usage_monitor.domain.enums import ProviderStatus

# Response captured from GetGrokCreditsConfig for a SuperGrok account:
# 37% overall, reset 2026-08-11 00:20:19 UTC.
GROK_CREDITS_RESPONSE = bytes.fromhex(
    "000000005f"
    "0a5d0d0000144212001a00220c08c3e0c4d3061088b7d69e03"
    "2a0c08c3d5e9d3061088b7d69e03"
    "3a0708021500001042"
    "3a070804150000803f"
    "421e0802120c08c3e0c4d3061088b7d69e03"
    "1a0c08c3d5e9d3061088b7d69e03"
    "580162006801"
    "800000000f677270632d7374617475733a300d0a"
)


def _auth_file(tmp_path, monkeypatch) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        '{"https://auth.x.ai::account": {"key": "test-bearer-token"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(grok_module, "GROK_AUTH_PATH", auth_path)


def test_grok_collector_uses_supergrok_weekly_grpc_endpoint(tmp_path, monkeypatch) -> None:
    _auth_file(tmp_path, monkeypatch)
    collector = GrokCollector()

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GROK_CREDITS_CONFIG_ENDPOINT).respond(
            200,
            content=GROK_CREDITS_RESPONSE,
            headers={"content-type": "application/grpc-web+proto"},
        )
        snapshot = collector.collect()

    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-bearer-token"
    assert request.headers["Content-Type"] == "application/grpc-web+proto"
    assert request.content == GROK_GRPC_WEB_REQUEST
    assert snapshot.status == ProviderStatus.OK
    assert snapshot.quota_windows[0].used_percent == 37
    assert snapshot.quota_windows[0].resets_at == datetime(
        2026, 8, 11, 0, 20, 19, 869637, tzinfo=timezone.utc
    )
def test_grok_credits_parser_reads_overall_percent_and_ignores_grpc_trailer() -> None:
    config = GrokCollector._parse_credits_config(GROK_CREDITS_RESPONSE)

    assert config.used_percent == 37
    assert config.period_end == datetime(
        2026, 8, 11, 0, 20, 19, 869637, tzinfo=timezone.utc
    )


def test_grok_collector_requires_fixed_auth_file(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing-auth.json"
    monkeypatch.setattr(grok_module, "GROK_AUTH_PATH", missing_path)

    snapshot = GrokCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "GROK_AUTH_NOT_CONFIGURED"


def test_grok_collector_surfaces_expired_auth(tmp_path, monkeypatch) -> None:
    _auth_file(tmp_path, monkeypatch)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(GROK_CREDITS_CONFIG_ENDPOINT).respond(401)
        snapshot = GrokCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
