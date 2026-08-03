from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ai_usage_monitor.domain.models import UsageSnapshot

from .paths import get_paths


class UsageDatabase:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_paths().database_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA user_version = 1")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    last_success_at TEXT,
                    message TEXT,
                    error_code TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                    quota_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    used_percent REAL,
                    used_value TEXT,
                    limit_value TEXT,
                    remaining_value TEXT,
                    unit TEXT,
                    window_minutes INTEGER,
                    resets_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                    currency TEXT NOT NULL,
                    total TEXT,
                    remaining TEXT,
                    used TEXT,
                    granted TEXT,
                    topped_up TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    alert_key TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    emitted_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save_snapshot(self, snapshot: UsageSnapshot) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots (
                    provider_id,
                    source_type,
                    status,
                    collected_at,
                    last_success_at,
                    message,
                    error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.provider_id,
                    snapshot.source_type.value,
                    snapshot.status.value,
                    snapshot.collected_at.isoformat(),
                    snapshot.last_success_at.isoformat() if snapshot.last_success_at else None,
                    snapshot.message,
                    snapshot.error_code,
                ),
            )
            snapshot_id = cursor.lastrowid
            for quota in snapshot.quota_windows:
                conn.execute(
                    """
                    INSERT INTO quota_windows (
                        snapshot_id, quota_key, label, used_percent, used_value, limit_value,
                        remaining_value, unit, window_minutes, resets_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        quota.key,
                        quota.label,
                        quota.used_percent,
                        str(quota.used_value) if quota.used_value is not None else None,
                        str(quota.limit_value) if quota.limit_value is not None else None,
                        str(quota.remaining_value) if quota.remaining_value is not None else None,
                        quota.unit,
                        quota.window_minutes,
                        quota.resets_at.isoformat() if quota.resets_at else None,
                    ),
                )
            for balance in snapshot.balances:
                conn.execute(
                    """
                    INSERT INTO credit_balances (
                        snapshot_id, currency, total, remaining, used, granted, topped_up
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        balance.currency,
                        str(balance.total) if balance.total is not None else None,
                        str(balance.remaining) if balance.remaining is not None else None,
                        str(balance.used) if balance.used is not None else None,
                        str(balance.granted) if balance.granted is not None else None,
                        str(balance.topped_up) if balance.topped_up is not None else None,
                    ),
                )
            conn.commit()
        return int(snapshot_id)

    def prune_old_records(self, max_age_days: int = 90) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM snapshots WHERE collected_at < ?",
                (datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(),),
            )
            conn.commit()
        return cursor.rowcount
