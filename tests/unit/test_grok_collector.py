from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
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


def _auth_file(
    tmp_path,
    monkeypatch,
    *,
    token: str = "test-bearer-token",
    expires_at: datetime | None = None,
    refresh_token: str | None = None,
):
    auth_path = tmp_path / "auth.json"
    account: dict[str, object] = {"key": token}
    if expires_at is not None:
        account["expires_at"] = expires_at.isoformat().replace("+00:00", "Z")
    if refresh_token is not None:
        account["refresh_token"] = refresh_token
    auth_path.write_text(
        json.dumps({"https://auth.x.ai::account": account}),
        encoding="utf-8",
    )
    monkeypatch.setattr(grok_module, "GROK_AUTH_PATH", auth_path)
    return auth_path


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
    assert config.period_end == datetime(2026, 8, 11, 0, 20, 19, 869637, tzinfo=timezone.utc)


def test_grok_collector_requires_fixed_auth_file(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing-auth.json"
    monkeypatch.setattr(grok_module, "GROK_AUTH_PATH", missing_path)

    snapshot = GrokCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "GROK_AUTH_NOT_CONFIGURED"


def test_grok_collector_refreshes_expired_auth_before_usage(tmp_path, monkeypatch) -> None:
    auth_path = _auth_file(
        tmp_path,
        monkeypatch,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        refresh_token="test-refresh-token",
    )
    collector = GrokCollector()
    refresh_calls = 0

    def refresh_auth() -> bool:
        nonlocal refresh_calls
        refresh_calls += 1
        auth_path.write_text(
            json.dumps(
                {
                    "https://auth.x.ai::account": {
                        "key": "refreshed-bearer-token",
                        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                        "refresh_token": "rotated-refresh-token",
                    }
                }
            ),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(collector, "_refresh_auth_with_cli", refresh_auth)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GROK_CREDITS_CONFIG_ENDPOINT).respond(
            200,
            content=GROK_CREDITS_RESPONSE,
        )
        snapshot = collector.collect()

    assert refresh_calls == 1
    assert route.calls[0].request.headers["Authorization"] == "Bearer refreshed-bearer-token"
    assert snapshot.status == ProviderStatus.OK


def test_grok_collector_refreshes_and_retries_after_401(tmp_path, monkeypatch) -> None:
    auth_path = _auth_file(
        tmp_path,
        monkeypatch,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        refresh_token="test-refresh-token",
    )
    collector = GrokCollector()

    def refresh_auth() -> bool:
        auth_path.write_text(
            json.dumps(
                {
                    "https://auth.x.ai::account": {
                        "key": "refreshed-bearer-token",
                        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                        "refresh_token": "rotated-refresh-token",
                    }
                }
            ),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(collector, "_refresh_auth_with_cli", refresh_auth)

    def usage_response(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer test-bearer-token":
            return httpx.Response(401)
        return httpx.Response(200, content=GROK_CREDITS_RESPONSE)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GROK_CREDITS_CONFIG_ENDPOINT).mock(side_effect=usage_response)
        snapshot = collector.collect()

    assert route.call_count == 2
    assert route.calls[1].request.headers["Authorization"] == "Bearer refreshed-bearer-token"
    assert snapshot.status == ProviderStatus.OK


def test_grok_collector_reports_failed_automatic_refresh(tmp_path, monkeypatch) -> None:
    _auth_file(
        tmp_path,
        monkeypatch,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        refresh_token="test-refresh-token",
    )
    collector = GrokCollector()
    monkeypatch.setattr(collector, "_refresh_auth_with_cli", lambda: False)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(GROK_CREDITS_CONFIG_ENDPOINT).respond(401)
        snapshot = collector.collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_REFRESH_FAILED"


def test_grok_auth_refresh_runs_official_cli_headlessly(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(grok_module.shutil, "which", lambda command: "grok-test.exe")

    def run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(grok_module.subprocess, "run", run)

    assert GrokCollector._refresh_auth_with_cli() is True
    assert captured["command"] == ["grok-test.exe", "models"]
    assert captured["stdin"] == grok_module.subprocess.DEVNULL
    assert captured["stdout"] == grok_module.subprocess.DEVNULL
    assert captured["stderr"] == grok_module.subprocess.DEVNULL
    assert captured["timeout"] == grok_module.GROK_CLI_TIMEOUT_SECONDS
    assert captured["env"]["GROK_HOME"] == str(grok_module.GROK_CONFIG_DIR)


def test_grok_collector_surfaces_auth_failure_without_refresh_token(tmp_path, monkeypatch) -> None:
    _auth_file(tmp_path, monkeypatch)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(GROK_CREDITS_CONFIG_ENDPOINT).respond(401)
        snapshot = GrokCollector().collect()

    assert snapshot.status == ProviderStatus.AUTH_REQUIRED
    assert snapshot.error_code == "AUTH_FAILED"
