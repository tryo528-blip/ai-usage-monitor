# AI Usage Monitor

A local Windows desktop dashboard for monitoring AI provider usage limits, balances, and status.

## Features

- Cards use two-character codes: provider letter + window (`5` = five hours, `W` = weekly)

  | Code | Source |
  |---|---|
  | `C5` / `CW` / `FW` | Claude 5h / Claude weekly / Fable weekly (Claude CLI `/usage`) |
  | `G5` / `GW` | Codex 5h / weekly (local `codex app-server`) |
  | `GR` | Grok weekly (CLI auth + billing endpoints) |
  | `A5` / `AW` | Antigravity (Gemini) 5h / weekly (`agy` CLI) |
  | `OR` | OpenRouter balance (Management Key) |

- Main window: ring-gauge cards. Hue identifies the provider, the clockwise arc shows the
  remaining quota, and the number turns amber/red at 20%/5% remaining.
- Windows taskbar: up to three providers are pinned to the notification area next to the clock
  as small tiles showing the code above a two-digit remaining number (100 reads `99`, 7 reads
  `07`). The default is `C5` · `CW` · `FW`; change it in Settings → `작업 표시줄`. With tray
  icons active, the close button hides the window to the tray; use the tray menu's `종료` to quit.
- Keyring-backed secret storage on Windows
- SQLite history retention

## Development setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## Run

```powershell
python -m ai_usage_monitor
```

## Test and lint

```powershell
pytest -q
ruff check .
ruff format --check .
```

## Notes

- No production credentials are stored in the repository.
- Codex usage reads live rate limits from the signed-in local `codex app-server`. Local session
  snapshots are a fallback, and already-expired quota windows are ignored.
- Claude usage first reads the same data as claude.ai Settings → Usage from
  `api.anthropic.com/api/oauth/usage`, using the Claude Code login token in
  `C:\Users\sswce\.claude\.credentials.json` (sent only to Anthropic, never stored or shown).
  When the token is missing or expired it falls back to running hidden `claude -p /usage` and
  parsing the English or Korean session/week/Fable lines.
- `python -m ai_usage_monitor --claude-raw` prints the raw usage API JSON and CLI output, to
  check which bucket holds the Fable weekly limit.
- Grok usage reads the fixed CLI auth file `C:\Users\sswce\.grok\auth.json` and polls authenticated
  Grok billing endpoints. The token is never displayed or stored in this repository.
- Settings provides `Claude 인증` (`claude auth login`) and `Grok 인증` (`grok login`) buttons.
- AntyG usage reads the local `agy -p /usage --output-format json` command. Sign in to
  Antigravity once before refreshing the card. A separate `/credits` request is intentionally
  skipped because credits are optional and should not delay or mark the quota cards critical.
- Fable weekly (`FW`) is any usage-API bucket whose key mentions `fable`, or the `이번 주 Fable` /
  `Current week (Fable …)` line in CLI output.
- Windows 11 hides new tray icons in the overflow (^) menu by default. Drag them onto the
  taskbar, or enable them under Settings → Personalization → Taskbar → Other system tray icons.
- Automatic refresh runs every 10 minutes. Claude percentages come from the CLI `/usage` output.
