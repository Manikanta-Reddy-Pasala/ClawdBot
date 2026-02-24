import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config import config


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: int
    chat_id: int
    context: str
    prompt: str
    status: TaskStatus
    result: Optional[str] = None
    tools_used: int = 0
    status_message_id: Optional[int] = None
    multi_agent: bool = False
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class TaskQueue:
    def __init__(self, db_path: str = config.DB_PATH):
        self._db_path = db_path
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
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                context TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                tools_used INTEGER DEFAULT 0,
                status_message_id INTEGER,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, context)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_chat ON tasks(chat_id, created_at)"
        )
        # Migration: add multi_agent column if missing
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN multi_agent INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            chat_id=row["chat_id"],
            context=row["context"],
            prompt=row["prompt"],
            status=TaskStatus(row["status"]),
            result=row["result"],
            tools_used=row["tools_used"],
            status_message_id=row["status_message_id"],
            multi_agent=bool(row["multi_agent"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def add(self, chat_id: int, context: str, prompt: str,
            status_message_id: int = None, multi_agent: bool = False) -> Task:
        now = time.time()
        conn = self._get_conn()
        with self._lock:
            cursor = conn.execute(
                """INSERT INTO tasks (chat_id, context, prompt, status, status_message_id, multi_agent, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, context, prompt, TaskStatus.PENDING.value,
                 status_message_id, int(multi_agent), now),
            )
            conn.commit()
            task_id = cursor.lastrowid
        return Task(
            id=task_id,
            chat_id=chat_id,
            context=context,
            prompt=prompt,
            status=TaskStatus.PENDING,
            status_message_id=status_message_id,
            multi_agent=multi_agent,
            created_at=now,
        )

    def get_next_pending(self, busy_contexts: set[str]) -> Optional[Task]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at ASC",
            (TaskStatus.PENDING.value,),
        ).fetchall()
        for row in rows:
            if row["context"] not in busy_contexts:
                return self._row_to_task(row)
        return None

    def set_running(self, task_id: int):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE tasks SET status = ?, started_at = ? WHERE id = ?",
                (TaskStatus.RUNNING.value, time.time(), task_id),
            )
            conn.commit()

    def set_completed(self, task_id: int, result: str, tools_used: int):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE tasks SET status = ?, result = ?, tools_used = ?, finished_at = ? WHERE id = ?",
                (TaskStatus.COMPLETED.value, result, tools_used, time.time(), task_id),
            )
            conn.commit()

    def set_failed(self, task_id: int, error: str):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE tasks SET status = ?, result = ?, finished_at = ? WHERE id = ?",
                (TaskStatus.FAILED.value, error, time.time(), task_id),
            )
            conn.commit()

    def set_cancelled(self, task_id: int):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE tasks SET status = ?, finished_at = ? WHERE id = ?",
                (TaskStatus.CANCELLED.value, time.time(), task_id),
            )
            conn.commit()

    def update_status_message_id(self, task_id: int, message_id: int):
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE tasks SET status_message_id = ? WHERE id = ?",
                (message_id, task_id),
            )
            conn.commit()

    def get_task(self, task_id: int) -> Optional[Task]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def get_running_for_context(self, context: str) -> Optional[Task]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE context = ? AND status = ? LIMIT 1",
            (context, TaskStatus.RUNNING.value),
        ).fetchone()
        return self._row_to_task(row) if row else None

    def get_pending_count(self, context: str) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE context = ? AND status = ?",
            (context, TaskStatus.PENDING.value),
        ).fetchone()
        return row["cnt"]

    def get_recent(self, chat_id: int, limit: int = 10) -> list[Task]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def cancel_pending_for_context(self, context: str) -> int:
        conn = self._get_conn()
        with self._lock:
            cursor = conn.execute(
                "UPDATE tasks SET status = ?, finished_at = ? WHERE context = ? AND status = ?",
                (TaskStatus.CANCELLED.value, time.time(), context, TaskStatus.PENDING.value),
            )
            conn.commit()
            return cursor.rowcount

    def get_all_running(self) -> list[Task]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ?",
            (TaskStatus.RUNNING.value,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]
