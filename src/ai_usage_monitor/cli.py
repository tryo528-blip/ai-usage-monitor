from __future__ import annotations

import sys

from ai_usage_monitor.collectors.antyg_bridge import AntigravityCollector
from ai_usage_monitor.collectors.claude_bridge import ClaudeBridgeCollector
from ai_usage_monitor.collectors.codex_app_server import CodexAppServerCollector
from ai_usage_monitor.collectors.grok import GrokCollector
from ai_usage_monitor.collectors.openrouter import OpenRouterCollector
from ai_usage_monitor.domain.enums import ProviderStatus
from ai_usage_monitor.domain.models import UsageSnapshot
from ai_usage_monitor.infrastructure.secret_store import SecretStore


def _format_snapshot(snapshot: UsageSnapshot) -> str:
    lines = [f"[{snapshot.provider_name}] {snapshot.status.value}"]
    for quota in snapshot.quota_windows:
        if quota.used_percent is None:
            continue
        remaining = max(0.0, 100.0 - quota.used_percent)
        reset = ""
        if quota.resets_at is not None:
            reset = f"  (리셋 {quota.resets_at.astimezone().strftime('%m-%d %H:%M')})"
        lines.append(f"  {quota.label}: {remaining:.0f}% 남음{reset}")
    for balance in snapshot.balances:
        amount = balance.remaining if balance.remaining is not None else balance.total
        if amount is not None:
            lines.append(f"  잔액: {amount} {balance.currency}")
    if snapshot.status is not ProviderStatus.OK and snapshot.message:
        lines.append(f"  ! {snapshot.message}")
    return "\n".join(lines)


# Account identifiers only; model and feature names stay readable.
_REDACT_MARKERS = ("uuid", "email", "org", "account", "token")


def _is_identifier(key: object) -> bool:
    name = str(key).lower()
    return name.endswith("_id") or any(marker in name for marker in _REDACT_MARKERS)


def redact_identifiers(value):
    """Mask account-identifying fields so the dump is safe to paste anywhere."""

    if isinstance(value, dict):
        return {
            key: "***"
            if _is_identifier(key) and not isinstance(val, (dict, list))
            else redact_identifiers(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [redact_identifiers(item) for item in value]
    return value


def _describe_credentials(now) -> tuple[list[str], str | None]:
    """Explain the stored Claude Code login without ever printing the token."""

    import json
    from datetime import datetime, timezone

    from ai_usage_monitor.collectors import claude_bridge

    path = claude_bridge.CLAUDE_CONFIG_DIR / ".credentials.json"
    lines = [f"credentials file : {path}"]
    if not path.exists():
        lines.append("  -> MISSING")
        try:
            names = sorted(item.name for item in claude_bridge.CLAUDE_CONFIG_DIR.iterdir())
            lines.append(f"  files in {claude_bridge.CLAUDE_CONFIG_DIR}: {', '.join(names[:40])}")
        except OSError as exc:
            lines.append(f"  cannot list folder: {exc.__class__.__name__}")
        return lines, None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        lines.append(f"  -> unreadable ({exc.__class__.__name__})")
        return lines, None
    if not isinstance(data, dict):
        lines.append("  -> unexpected content")
        return lines, None
    lines.append(f"  top-level keys : {', '.join(map(str, data))}")
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        lines.append("  -> no claudeAiOauth section")
        return lines, None
    token = oauth.get("accessToken")
    token = token if isinstance(token, str) and token else None
    lines.append(f"  accessToken    : {'present' if token else 'MISSING'}")
    lines.append(f"  refreshToken   : {'present' if oauth.get('refreshToken') else 'missing'}")
    expires_at = oauth.get("expiresAt")
    if isinstance(expires_at, (int, float)) and expires_at > 0:
        expiry = datetime.fromtimestamp(expires_at / 1000, tz=timezone.utc)
        minutes = round((expiry - now).total_seconds() / 60)
        state = f"valid for {minutes} min" if minutes > 0 else f"EXPIRED {-minutes} min ago"
        lines.append(f"  expiresAt      : {expiry.astimezone():%Y-%m-%d %H:%M} ({state})")
    else:
        lines.append(f"  expiresAt      : {expires_at!r}")
    for key in ("scopes", "subscriptionType", "rateLimitTier"):
        if key in oauth:
            lines.append(f"  {key:<15}: {oauth[key]}")
    return lines, token


def dump_claude_raw() -> int:
    """Print what the Claude collector sees, to find why Claude reads "--"."""

    import json
    from datetime import datetime, timezone

    import httpx

    from ai_usage_monitor.collectors import claude_bridge

    now = datetime.now(timezone.utc)
    print("=== Claude Code login ===")
    lines, token = _describe_credentials(now)
    print("\n".join(lines))
    print()
    print(f"=== usage API ({claude_bridge.USAGE_API_URL}) ===")
    if token is None:
        print("(skipped: no access token)")
    else:
        # Tried even when expired so the server's answer is visible.
        try:
            response = httpx.get(
                claude_bridge.USAGE_API_URL,
                headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
                timeout=claude_bridge.USAGE_API_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            print(f"request failed: {exc.__class__.__name__}: {exc}")
        else:
            print(f"HTTP {response.status_code}")
            try:
                body = redact_identifiers(response.json())
                print(json.dumps(body, ensure_ascii=False, indent=2)[:4000])
            except ValueError:
                print(response.text[:500])
            quotas = claude_bridge.ClaudeBridgeCollector._parse_usage_json(
                response.json() if response.is_success else None
            )
            print("parsed:", [(q.key, q.used_percent) for q in quotas] or "nothing")
    print()
    print("=== claude -p /usage ===")
    try:
        output = claude_bridge.ClaudeBridgeCollector._run_usage()
        print(output)
        if "Total cost:" in output:
            print("-> this CLI prints the cost summary for /usage in -p mode, not the limits")
    except Exception as exc:  # noqa: BLE001 - diagnostics must always finish
        print(f"(failed: {exc})")
    return 0


def main() -> int:
    if "--claude-raw" in sys.argv:
        return dump_claude_raw()
    secret_store = SecretStore()
    collectors = [
        AntigravityCollector(),
        ClaudeBridgeCollector(),
        CodexAppServerCollector(),
        GrokCollector(),
        OpenRouterCollector(secret_store=secret_store),
    ]

    exit_code = 0
    for collector in collectors:
        try:
            snapshot = collector.collect()
        except Exception as exc:  # noqa: BLE001 - CLI must never crash on one provider
            print(f"[{collector.provider_name}] 수집 실패: {exc}")
            exit_code = 1
            continue
        print(_format_snapshot(snapshot))
        if snapshot.status is not ProviderStatus.OK:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
