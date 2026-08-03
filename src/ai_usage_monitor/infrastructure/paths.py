from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import AppDirs

APP_DIRS = AppDirs("AIUsageMonitor", "AIUsageMonitor")


@dataclass(frozen=True)
class AppPaths:
    appdata_dir: Path
    local_appdata_dir: Path
    settings_path: Path
    database_path: Path
    log_path: Path
    bridge_dir: Path


def get_paths() -> AppPaths:
    appdata_dir = Path(APP_DIRS.user_data_dir)
    local_appdata_dir = Path(APP_DIRS.user_data_path)
    settings_path = appdata_dir / "settings.json"
    database_path = local_appdata_dir / "usage.db"
    log_path = local_appdata_dir / "logs" / "app.log"
    bridge_dir = local_appdata_dir / "bridges"
    return AppPaths(
        appdata_dir=appdata_dir,
        local_appdata_dir=local_appdata_dir,
        settings_path=settings_path,
        database_path=database_path,
        log_path=log_path,
        bridge_dir=bridge_dir,
    )
