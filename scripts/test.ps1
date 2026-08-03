Set-Location $PSScriptRoot\..
pytest -q
ruff check .
ruff format --check .
