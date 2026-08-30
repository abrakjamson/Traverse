from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CacheEntry:
    url: str
    body: bytes
    fetched_at: float
    etag: str | None
    last_modified: str | None
    content_type: str | None

    def is_fresh(self, ttl_seconds: int) -> bool:
        return time.time() - self.fetched_at <= ttl_seconds


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                url TEXT PRIMARY KEY,
                body BLOB NOT NULL,
                fetched_at REAL NOT NULL,
                etag TEXT,
                last_modified TEXT,
                content_type TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        self._lock = threading.Lock()

    def get(self, url: str) -> CacheEntry | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT url, body, fetched_at, etag, last_modified, content_type FROM pages WHERE url = ?",
                (url,),
            ).fetchone()
        return CacheEntry(*row) if row else None

    def put(
        self,
        url: str,
        body: bytes,
        *,
        etag: str | None,
        last_modified: str | None,
        content_type: str | None,
        fetched_at: float | None = None,
    ) -> CacheEntry:
        timestamp = fetched_at if fetched_at is not None else time.time()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO pages(url, body, fetched_at, etag, last_modified, content_type)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    body = excluded.body,
                    fetched_at = excluded.fetched_at,
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    content_type = excluded.content_type
                """,
                (url, body, timestamp, etag, last_modified, content_type),
            )
            self._connection.commit()
        return CacheEntry(url, body, timestamp, etag, last_modified, content_type)

    def touch(self, entry: CacheEntry) -> CacheEntry:
        return self.put(
            entry.url,
            entry.body,
            etag=entry.etag,
            last_modified=entry.last_modified,
            content_type=entry.content_type,
        )

    def get_state(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_state(self, key: str, value: dict[str, Any]) -> None:
        serialized = json.dumps(value, separators=(",", ":"))
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, serialized),
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
