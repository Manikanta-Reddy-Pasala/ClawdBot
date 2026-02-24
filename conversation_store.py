import sqlite3
import json
import threading
from config import config


class ConversationStore:
    def __init__(self, db_path: str = config.DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_id ON messages(chat_id, created_at)"
        )
        conn.commit()

    def add_message(self, chat_id: int, role: str, content: str, model: str = None):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO messages (chat_id, role, content, model) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, model),
        )
        conn.commit()

    def get_history(self, chat_id: int, limit: int = config.CONTEXT_WINDOW) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, created_at
                FROM messages
                WHERE chat_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ) sub ORDER BY created_at ASC
            """,
            (chat_id, limit),
        ).fetchall()
        return [{"role": row[0], "content": row[1]} for row in rows]

    def clear_history(self, chat_id: int):
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.commit()

    def get_stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        chats = conn.execute("SELECT COUNT(DISTINCT chat_id) FROM messages").fetchone()[0]
        return {"total_messages": total, "total_chats": chats}
