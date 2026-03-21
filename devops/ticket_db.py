"""Persistent ticket storage using SQLite."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("TICKET_DB_PATH", "/opt/clawdbot/tickets.db")
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Initialize the database schema."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            service TEXT,
            namespace TEXT,
            severity TEXT,
            category TEXT,
            description TEXT,
            matched_line TEXT,
            recommendation TEXT,
            status TEXT DEFAULT 'created',
            created_at TEXT,
            updated_at TEXT,
            clawdbot_task_id TEXT,
            clawdbot_output TEXT,
            mr_url TEXT,
            telegram_notified INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at);

        CREATE TABLE IF NOT EXISTS passkey_credentials (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            public_key BLOB NOT NULL,
            sign_count INTEGER DEFAULT 0,
            created_at TEXT
        );
    """)
    conn.commit()
    logger.info("Ticket database initialized at %s", DB_PATH)


def create_ticket(
    service: str,
    namespace: str,
    severity: str,
    category: str,
    description: str,
    matched_line: str,
    recommendation: str = "",
) -> dict:
    """Create a ticket and return it as a dict."""
    conn = _get_conn()
    uid = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    cursor = conn.execute(
        """INSERT INTO tickets (uid, service, namespace, severity, category,
           description, matched_line, recommendation, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?)""",
        (uid, service, namespace, severity, category,
         description, matched_line, recommendation, now, now),
    )
    conn.commit()
    return _row_to_dict(conn.execute("SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_ticket(ticket_id: int, updates: dict) -> dict | None:
    """Update a ticket's fields. Returns updated ticket or None."""
    conn = _get_conn()
    allowed = {"status", "clawdbot_task_id", "clawdbot_output", "mr_url", "telegram_notified"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return get_ticket(ticket_id)
    filtered["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [ticket_id]
    conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_ticket(ticket_id)


def get_ticket(ticket_id: int) -> dict | None:
    """Get a single ticket by ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_tickets(status: str | None = None, service: str | None = None,
                severity: str | None = None, limit: int = 50) -> list[dict]:
    """Get tickets with optional filters."""
    conn = _get_conn()
    query = "SELECT * FROM tickets WHERE 1=1"
    params = []
    if status and status != "all":
        query += " AND status = ?"
        params.append(status)
    if service:
        query += " AND service = ?"
        params.append(service)
    if severity:
        query += " AND severity = ?"
        params.append(severity)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def reset_all_tickets() -> int:
    """Delete ALL tickets. Returns count of deleted tickets."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    conn.execute("DELETE FROM tickets")
    conn.commit()
    logger.info("Reset all tickets: deleted %d", count)
    return count


def cleanup_old_tickets(days: int = 90):
    """Delete tickets older than N days. If >1000 tickets, use 30 days."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    cutoff_days = 30 if count > 1000 else days
    cutoff = (datetime.utcnow() - timedelta(days=cutoff_days)).isoformat()
    result = conn.execute("DELETE FROM tickets WHERE created_at < ?", (cutoff,))
    conn.commit()
    deleted = result.rowcount
    if deleted > 0:
        logger.info("Cleaned up %d tickets older than %d days", deleted, cutoff_days)
    return deleted


def get_ticket_stats() -> dict:
    """Get ticket statistics for dashboard overview."""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved', 'closed')"
    ).fetchone()[0]
    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM tickets GROUP BY status"):
        by_status[row["status"]] = row["cnt"]
    by_severity = {}
    for row in conn.execute(
        "SELECT severity, COUNT(*) as cnt FROM tickets WHERE status NOT IN ('resolved', 'closed') GROUP BY severity"
    ):
        by_severity[row["severity"]] = row["cnt"]
    ai_fixed = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE status = 'resolved' AND clawdbot_output IS NOT NULL AND clawdbot_output != ''"
    ).fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'resolved'").fetchone()[0]
    return {"total": total, "active": active, "resolved": resolved, "ai_fixed": ai_fixed, "by_status": by_status, "by_severity": by_severity}


# --- Passkey credential storage ---

def save_passkey_credential(credential_id: str, user_id: str, public_key: bytes, sign_count: int = 0):
    """Store a WebAuthn credential."""
    conn = _get_conn()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO passkey_credentials (id, user_id, public_key, sign_count, created_at) VALUES (?, ?, ?, ?, ?)",
        (credential_id, user_id, public_key, sign_count, now),
    )
    conn.commit()


def get_passkey_credential(credential_id: str) -> dict | None:
    """Get a stored credential by ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM passkey_credentials WHERE id = ?", (credential_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "user_id": row["user_id"], "public_key": bytes(row["public_key"]),
            "sign_count": row["sign_count"], "created_at": row["created_at"]}


def get_passkey_credentials_for_user(user_id: str) -> list[dict]:
    """Get all credentials for a user."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM passkey_credentials WHERE user_id = ?", (user_id,)).fetchall()
    return [{"id": r["id"], "user_id": r["user_id"], "public_key": bytes(r["public_key"]),
             "sign_count": r["sign_count"], "created_at": r["created_at"]} for r in rows]


def update_passkey_sign_count(credential_id: str, sign_count: int):
    """Update the sign count after successful auth."""
    conn = _get_conn()
    conn.execute("UPDATE passkey_credentials SET sign_count = ? WHERE id = ?", (sign_count, credential_id))
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a dict."""
    return dict(row)
