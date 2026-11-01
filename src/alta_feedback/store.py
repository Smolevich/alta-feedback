"""SQLite-хранилище правок и отчётов об открытии счетов."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alta_feedback.accounts import AccountReport
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

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    bank TEXT NOT NULL,
    city TEXT NOT NULL,
    account_type TEXT NOT NULL,
    result TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    residency TEXT NOT NULL,
    documents TEXT NOT NULL,
    comment TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    user_agent_short TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS accounts_ip_time ON accounts (ip_hash, created_at);
CREATE INDEX IF NOT EXISTS accounts_time ON accounts (created_at);
CREATE INDEX IF NOT EXISTS accounts_status ON accounts (status);

CREATE TABLE IF NOT EXISTS pow_used (
    challenge TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL
);
"""

COLUMNS = {
    "suggestions": (
        "id", "created_at", "section_id", "section_title", "text",
        "source", "contact", "ip_hash", "user_agent_short", "status",
    ),
    "accounts": (
        "id", "created_at", "bank", "city", "account_type", "result", "visit_date",
        "residency", "documents", "comment", "ip_hash", "user_agent_short", "status",
    ),
}
PUBLIC_ACCOUNT_COLUMNS = (
    "id", "visit_date", "bank", "city", "account_type", "result", "residency", "documents", "comment",
)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    if "documents" in item:
        item["documents"] = json.loads(item["documents"])
    return item


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

    def add_account(self, item: AccountReport, ip_hash: str, user_agent: str, now: datetime) -> int:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO accounts (created_at, bank, city, account_type, result, visit_date,"
                " residency, documents, comment, ip_hash, user_agent_short)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iso(now), item.bank, item.city, item.account_type, item.result, item.visit_date,
                 item.residency, json.dumps(list(item.documents)), item.comment, ip_hash, user_agent),
            )
            return int(cur.lastrowid or 0)

    def recent_from(
        self, ip_hash: str, now: datetime, window: timedelta, table: str = "suggestions"
    ) -> int:
        if table not in COLUMNS:
            raise ValueError(f"unknown table {table}")
        with self.connect() as db:
            row = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ip_hash = ? AND created_at > ?",
                (ip_hash, iso(now - window)),
            ).fetchone()
            return int(row[0])

    def since(self, moment: str, status: str | None, limit: int, table: str = "suggestions") -> list[dict]:
        query = f"SELECT {', '.join(COLUMNS[table])} FROM {table} WHERE created_at > ?"
        args: list[str | int] = [moment]
        if status:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY id LIMIT ?"
        args.append(limit)
        with self.connect() as db:
            return [decode_row(row) for row in db.execute(query, args)]

    def set_status(self, item_id: int, status: str, table: str = "suggestions") -> bool:
        if table not in COLUMNS:
            raise ValueError(f"unknown table {table}")
        with self.connect() as db:
            cur = db.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (status, item_id))
            return cur.rowcount == 1

    def public_accounts(self, limit: int) -> list[dict]:
        """Только принятые отчёты и только публичные поля, свежие визиты сверху."""
        query = (
            f"SELECT {', '.join(PUBLIC_ACCOUNT_COLUMNS)} FROM accounts WHERE status = 'accepted'"
            " ORDER BY visit_date DESC, id DESC LIMIT ?"
        )
        with self.connect() as db:
            return [decode_row(row) for row in db.execute(query, (limit,))]

    def claim_challenge(self, challenge: str, expires_at: int, now: datetime) -> bool:
        """Отмечает решённую задачу использованной; False — её уже предъявляли."""
        with self.connect() as db:
            db.execute("DELETE FROM pow_used WHERE expires_at < ?", (int(now.timestamp()),))
            cur = db.execute(
                "INSERT OR IGNORE INTO pow_used (challenge, expires_at) VALUES (?, ?)",
                (challenge, expires_at),
            )
            return cur.rowcount == 1

    def forget_old_traces(self, before: datetime) -> None:
        """Стирает хэш IP и браузер у записей старше срока: лимиту частоты они нужны лишь час."""
        with self.connect() as db:
            for table in COLUMNS:
                db.execute(
                    f"UPDATE {table} SET ip_hash = '', user_agent_short = ''"
                    " WHERE created_at < ? AND (ip_hash != '' OR user_agent_short != '')",
                    (iso(before),),
                )
