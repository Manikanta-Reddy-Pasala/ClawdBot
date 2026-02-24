import os
import sqlite3
import threading

from config import config

DEFAULT_CONTEXT = "vm"


class ContextManager:
    def __init__(self, db_path: str = config.DB_PATH, repos_dir: str = config.REPOS_DIR):
        self._db_path = db_path
        self._repos_dir = repos_dir
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_context (
                chat_id INTEGER PRIMARY KEY,
                context TEXT NOT NULL DEFAULT 'vm'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_contexts (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                context TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_chat_ctx "
            "ON conversation_history(chat_id, context, created_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claude_sessions (
                chat_id INTEGER NOT NULL,
                context TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, context)
            )
        """)
        conn.commit()

    def resolve_repo_path(self, name: str) -> str | None:
        """Fuzzy match a name to a repo directory (case-insensitive)."""
        if not os.path.isdir(self._repos_dir):
            return None
        dirs = os.listdir(self._repos_dir)
        # Exact match (case-insensitive)
        for d in dirs:
            if d.lower() == name.lower() and os.path.isdir(os.path.join(self._repos_dir, d)):
                return os.path.join(self._repos_dir, d)
        # Prefix match
        for d in sorted(dirs):
            if d.lower().startswith(name.lower()) and os.path.isdir(os.path.join(self._repos_dir, d)):
                return os.path.join(self._repos_dir, d)
        return None

    def add_custom_context(self, name: str, path: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO custom_contexts (name, path) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET path = ?",
                (name, path, path),
            )
            conn.commit()

    def remove_custom_context(self, name: str) -> bool:
        conn = self._get_conn()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM custom_contexts WHERE name = ?", (name,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_custom_contexts(self) -> dict[str, str]:
        conn = self._get_conn()
        rows = conn.execute("SELECT name, path FROM custom_contexts").fetchall()
        return {row["name"]: row["path"] for row in rows}

    def get_available_contexts(self) -> list[str]:
        contexts = [DEFAULT_CONTEXT]
        # Add auto-discovered repos
        if os.path.isdir(self._repos_dir):
            for name in sorted(os.listdir(self._repos_dir)):
                full = os.path.join(self._repos_dir, name)
                if os.path.isdir(full):
                    contexts.append(name)
        # Add custom contexts
        custom = self.get_custom_contexts()
        for name in sorted(custom.keys()):
            if name not in contexts:
                contexts.append(name)
        return contexts

    def get_active_context(self, chat_id: int) -> str:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT context FROM active_context WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row["context"] if row else DEFAULT_CONTEXT

    def set_active_context(self, chat_id: int, context: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO active_context (chat_id, context) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET context = ?",
                (chat_id, context, context),
            )
            conn.commit()

    def get_working_dir(self, context: str) -> str:
        if context == DEFAULT_CONTEXT:
            return "/opt/clawdbot"
        # Check custom contexts first
        custom = self.get_custom_contexts()
        if context in custom:
            return custom[context]
        # Then check repos
        repo_path = os.path.join(self._repos_dir, context)
        if os.path.isdir(repo_path):
            return repo_path
        return "/opt/clawdbot"

    def add_message(self, chat_id: int, context: str, role: str, content: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO conversation_history (chat_id, context, role, content) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, context, role, content),
            )
            conn.commit()

    def get_history(self, chat_id: int, context: str, limit: int = config.CONTEXT_WINDOW) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, created_at
                FROM conversation_history
                WHERE chat_id = ? AND context = ?
                ORDER BY created_at DESC
                LIMIT ?
            ) sub ORDER BY created_at ASC
            """,
            (chat_id, context, limit),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def clear_history(self, chat_id: int, context: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "DELETE FROM conversation_history WHERE chat_id = ? AND context = ?",
                (chat_id, context),
            )
            conn.execute(
                "DELETE FROM claude_sessions WHERE chat_id = ? AND context = ?",
                (chat_id, context),
            )
            conn.commit()

    def get_session_id(self, chat_id: int, context: str) -> str | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT session_id FROM claude_sessions WHERE chat_id = ? AND context = ?",
            (chat_id, context),
        ).fetchone()
        return row["session_id"] if row else None

    def set_session_id(self, chat_id: int, context: str, session_id: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT INTO claude_sessions (chat_id, context, session_id) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id, context) DO UPDATE SET session_id = ?, created_at = CURRENT_TIMESTAMP",
                (chat_id, context, session_id, session_id),
            )
            conn.commit()

    def clear_session(self, chat_id: int, context: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "DELETE FROM claude_sessions WHERE chat_id = ? AND context = ?",
                (chat_id, context),
            )
            conn.commit()
