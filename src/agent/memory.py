"""SQLite-backed conversation history persistence across multi-turn sessions."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionMemory:
    """Persistent multi-turn conversation store backed by SQLite."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
            )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Append a message turn to the given session."""
        now = datetime.now(timezone.utc).isoformat()
        tc_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_calls_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tc_json, now),
            )

    def get_history(self, session_id: str, max_turns: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent messages for a session."""
        rows = self.conn.execute(
            """
            SELECT role, content, tool_calls_json, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, max_turns),
        ).fetchall()

        history: list[dict[str, Any]] = []
        for r in reversed(rows):
            item: dict[str, Any] = {
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"],
            }
            if r["tool_calls_json"]:
                try:
                    item["tool_calls"] = json.loads(r["tool_calls_json"])
                except json.JSONDecodeError:
                    item["tool_calls"] = []
            history.append(item)
        return history

    def clear_session(self, session_id: str) -> None:
        """Delete all stored turns for a session."""
        with self.conn:
            self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

    def list_sessions(self) -> list[str]:
        """List all active session IDs."""
        rows = self.conn.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY id DESC"
        ).fetchall()
        return [str(r["session_id"]) for r in rows]
