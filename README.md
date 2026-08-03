# AI Usage Monitor

A local Windows desktop dashboard for monitoring AI provider usage limits, balances, and status.

## Features

- OpenRouter and DeepSeek collectors with official HTTP APIs
- Manual collectors for Grok and Gemini
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
- Claude and Codex integrations are intentionally stubbed as `UNAVAILABLE` placeholders for Phase 3.
