from __future__ import annotations

import json
from pathlib import Path

from .paths import get_paths


class SettingsStore:
    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or get_paths().settings_path
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.settings_path.exists():
            return {}
        with self.settings_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, settings: dict) -> None:
        with self.settings_path.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
