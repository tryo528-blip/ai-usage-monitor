# AI Usage Monitor

A local Windows desktop dashboard for monitoring AI provider usage limits, balances, and status.

## Features

- Claude Code local `ccusage` bridge, Grok weekly usage bridge, OpenRouter balance collector
  using a Management Key, plus DeepSeek official HTTP API
- Keyring-backed secret storage on Windows
- SQLite history retention
- Basic PySide6 desktop app shell with independent refresh workers

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
- Codex usage reads the latest local rate-limit snapshot from
  `C:\Users\sswce\.codex\sessions`.
- Claude usage reads the fixed Claude CLI config root `C:\Users\sswce\.claude` by running hidden
  `/usage` and parsing the session/week percentages and reset times.
- Grok usage reads the fixed CLI auth file `C:\Users\sswce\.grok\auth.json` and polls authenticated
  Grok billing endpoints. The token is never displayed or stored in this repository.
- Settings provides `Claude 인증` (`claude auth login`) and `Grok 인증` (`grok login`) buttons.
- Automatic refresh runs every 10 minutes. Claude percentages come from the CLI `/usage` output.
