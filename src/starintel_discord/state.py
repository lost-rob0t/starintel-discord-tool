from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class RadarSpec:
    id: int
    guild_id: int
    channel_id: int
    query: str
    dataset: str | None
    tenant_id: str | None
    source_dataset: str | None
    created_by: int
    enabled: bool
    bootstrapped: bool


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS radars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                dataset TEXT,
                tenant_id TEXT,
                source_dataset TEXT,
                created_by INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                bootstrapped INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS radar_seen (
                radar_id INTEGER NOT NULL,
                document_key TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY(radar_id, document_key),
                FOREIGN KEY(radar_id) REFERENCES radars(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS radar_seen_seen_at_idx ON radar_seen(seen_at);
            """
        )
        self._db.commit()

    def seed_authorized_users(self, user_ids: Iterable[int]) -> None:
        now = utc_now()
        self._db.executemany(
            "INSERT OR IGNORE INTO authorized_users(user_id, added_by, created_at) VALUES (?, ?, ?)",
            ((int(user_id), 0, now) for user_id in user_ids),
        )
        self._db.commit()

    def is_authorized(self, user_id: int) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM authorized_users WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return row is not None

    def add_authorized_user(self, user_id: int, added_by: int) -> None:
        self._db.execute(
            """
            INSERT INTO authorized_users(user_id, added_by, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET added_by=excluded.added_by, created_at=excluded.created_at
            """,
            (int(user_id), int(added_by), utc_now()),
        )
        self._db.commit()

    def remove_authorized_user(self, user_id: int) -> bool:
        cursor = self._db.execute("DELETE FROM authorized_users WHERE user_id = ?", (int(user_id),))
        self._db.commit()
        return cursor.rowcount > 0

    def list_authorized_users(self) -> tuple[int, ...]:
        rows = self._db.execute("SELECT user_id FROM authorized_users ORDER BY user_id").fetchall()
        return tuple(int(row["user_id"]) for row in rows)

    def upsert_radar(
        self,
        *,
        guild_id: int,
        channel_id: int,
        query: str,
        dataset: str | None,
        tenant_id: str | None,
        source_dataset: str | None,
        created_by: int,
    ) -> RadarSpec:
        now = utc_now()
        self._db.execute(
            """
            INSERT INTO radars(
                guild_id, channel_id, query, dataset, tenant_id, source_dataset,
                created_by, enabled, bootstrapped, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                query=excluded.query,
                dataset=excluded.dataset,
                tenant_id=excluded.tenant_id,
                source_dataset=excluded.source_dataset,
                created_by=excluded.created_by,
                enabled=1,
                bootstrapped=0,
                updated_at=excluded.updated_at
            """,
            (
                guild_id,
                channel_id,
                query,
                dataset,
                tenant_id,
                source_dataset,
                created_by,
                now,
                now,
            ),
        )
        row = self._db.execute(
            "SELECT * FROM radars WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
        assert row is not None
        radar_id = int(row["id"])
        self._db.execute("DELETE FROM radar_seen WHERE radar_id = ?", (radar_id,))
        self._db.commit()
        return self._row_to_radar(row)

    def disable_radar(self, guild_id: int, channel_id: int) -> bool:
        cursor = self._db.execute(
            "UPDATE radars SET enabled = 0, updated_at = ? WHERE guild_id = ? AND channel_id = ?",
            (utc_now(), guild_id, channel_id),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def list_radars(self, guild_id: int | None = None) -> tuple[RadarSpec, ...]:
        if guild_id is None:
            rows = self._db.execute("SELECT * FROM radars WHERE enabled = 1 ORDER BY id").fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM radars WHERE enabled = 1 AND guild_id = ? ORDER BY channel_id",
                (guild_id,),
            ).fetchall()
        return tuple(self._row_to_radar(row) for row in rows)

    def mark_bootstrapped(self, radar_id: int) -> None:
        self._db.execute(
            "UPDATE radars SET bootstrapped = 1, updated_at = ? WHERE id = ?",
            (utc_now(), radar_id),
        )
        self._db.commit()

    def remember_documents(self, radar_id: int, documents: Iterable[dict[str, Any]]) -> set[str]:
        new_keys: set[str] = set()
        now = utc_now()
        for document in documents:
            key = document_key(document)
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO radar_seen(radar_id, document_key, seen_at) VALUES (?, ?, ?)",
                (radar_id, key, now),
            )
            if cursor.rowcount > 0:
                new_keys.add(key)
        self._db.commit()
        return new_keys

    @staticmethod
    def _row_to_radar(row: sqlite3.Row) -> RadarSpec:
        return RadarSpec(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            query=str(row["query"]),
            dataset=str(row["dataset"]) if row["dataset"] is not None else None,
            tenant_id=str(row["tenant_id"]) if row["tenant_id"] is not None else None,
            source_dataset=str(row["source_dataset"]) if row["source_dataset"] is not None else None,
            created_by=int(row["created_by"]),
            enabled=bool(row["enabled"]),
            bootstrapped=bool(row["bootstrapped"]),
        )


def document_key(document: dict[str, Any]) -> str:
    for key in ("_id", "id", "document_id", "uuid"):
        value = document.get(key)
        if value not in (None, ""):
            return f"id:{value}"
    stable = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    import hashlib

    return "sha256:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()
