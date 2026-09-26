# Provider Support

Implemented in this phase:

- Claude Code usage via hidden CLI `/usage` bridge (`C:\Users\sswce\.claude`)
- Grok weekly usage via the fixed CLI auth file (`C:\Users\sswce\.grok\auth.json`) and authenticated billing endpoints
- Codex usage via the signed-in local app-server's `account/rateLimits/read`; unexpired
  `rate_limits` snapshots from the current user's session directory are a fallback
- Claude five-hour usage via the local Claude CLI `/usage` bridge
- AntyG (Google Antigravity/Gemini) reads the signed-in `agy` CLI's `/usage` quota output.
- OpenRouter balance via the Management Key.
- Claude's Fable-only weekly bucket, when the CLI `/usage` output includes it.

Removed: DeepSeek, Z.AI and Kimi.
