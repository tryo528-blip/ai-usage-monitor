# Provider Support

Implemented in this phase:

- Claude Code usage via hidden CLI `/usage` bridge (`C:\Users\sswce\.claude`)
- Grok weekly usage via the fixed CLI auth file (`C:\Users\sswce\.grok\auth.json`) and authenticated billing endpoints
- DeepSeek via official HTTP API
- Codex usage via the fixed local session path (`C:\Users\sswce\.codex\sessions`) and
  `rate_limits` snapshots emitted by Codex
- Claude five-hour usage via the local Claude CLI `/usage` bridge
- AntyG (Google Antigravity/Gemini) reads the signed-in `agy` CLI's `/usage` quota output.
  Z.AI and KIMI3 remain selectable UI cards without collectors and display an explicit
  placeholder rather than an invented usage value.
