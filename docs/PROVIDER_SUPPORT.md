# Provider Support

Implemented in this phase:

- Claude Code usage via hidden CLI `/usage` bridge (`C:\Users\sswce\.claude`)
- Grok weekly usage via the fixed CLI auth file (`C:\Users\sswce\.grok\auth.json`) and authenticated billing endpoints
- OpenRouter balance via the official `/credits` API using a Management Key
- DeepSeek via official HTTP API
- Codex usage via the fixed local session path (`C:\Users\sswce\.codex\sessions`) and
  `rate_limits` snapshots emitted by Codex
- Gemini remains outside the compact five-row UI
