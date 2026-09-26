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


def dump_claude_raw() -> int:
    """Print what the Claude collector sees, to check the Fable bucket's name."""

    import json
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    print("=== usage API (api.anthropic.com/api/oauth/usage) ===")
    data = ClaudeBridgeCollector.fetch_usage_json(now=now)
    if data is None:
        print("(no response: missing/expired token or request failed)")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    print()
    print("=== claude -p /usage ===")
    try:
        print(ClaudeBridgeCollector._run_usage())
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
