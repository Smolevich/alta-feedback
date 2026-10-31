"""SQLite-хранилище правок."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alta_feedback.validate import Suggestion

SCHEMA = """
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    section_id TEXT NOT NULL,
    section_title TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    contact TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    user_agent_short TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS suggestions_ip_time ON suggestions (ip_hash, created_at);
CREATE INDEX IF NOT EXISTS suggestions_time ON suggestions (created_at);
"""

COLUMNS = (
    "id", "created_at", "section_id", "section_title", "text",
    "source", "contact", "ip_hash", "user_agent_short", "status",
)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Соединение на одну операцию: коммит при успехе, закрытие всегда."""
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, item: Suggestion, ip_hash: str, user_agent: str, now: datetime) -> int:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO suggestions (created_at, section_id, section_title, text, source,"
                " contact, ip_hash, user_agent_short) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (iso(now), item.section_id, item.section_title, item.text, item.source,
                 item.contact, ip_hash, user_agent),
            )
            return int(cur.lastrowid or 0)

    def recent_from(self, ip_hash: str, now: datetime, window: timedelta) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM suggestions WHERE ip_hash = ? AND created_at > ?",
                (ip_hash, iso(now - window)),
            ).fetchone()
            return int(row[0])

    def since(self, moment: str, status: str | None, limit: int) -> list[dict]:
        query = f"SELECT {', '.join(COLUMNS)} FROM suggestions WHERE created_at > ?"
        args: list[str | int] = [moment]
        if status:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY id LIMIT ?"
        args.append(limit)
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, args)]

    def set_status(self, suggestion_id: int, status: str) -> bool:
        with self.connect() as db:
            cur = db.execute("UPDATE suggestions SET status = ? WHERE id = ?", (status, suggestion_id))
            return cur.rowcount == 1
