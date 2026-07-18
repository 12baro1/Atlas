"""
telegram_auth_store.py
Atlas Telegram user/auth persistence layer
"""

import sqlite3
from contextlib import contextmanager


class TelegramAuthStore:
    """Telegram kullanıcılarını güvenli şekilde SQLite üzerinde saklar."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    telegram_id INTEGER PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get_user(self, telegram_id):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT telegram_id, username, role, status FROM telegram_users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return {
            "telegram_id": row[0],
            "username": row[1],
            "role": row[2],
            "status": row[3],
        }

    def upsert_user(self, telegram_id, username, role, status="ACTIVE"):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO telegram_users (telegram_id, username, role, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    role = excluded.role,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (telegram_id, username, role, status),
            )

    def update_role(self, telegram_id, role):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE telegram_users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (role, telegram_id),
            )
            return cursor.rowcount > 0

    def update_status(self, telegram_id, status):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE telegram_users SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (status, telegram_id),
            )
            return cursor.rowcount > 0

    def delete_user(self, telegram_id):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM telegram_users WHERE telegram_id = ?", (telegram_id,))
            self.clear_session(telegram_id)
            return cursor.rowcount > 0

    def list_users(self):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT telegram_id, username, role, status FROM telegram_users ORDER BY created_at ASC"
            )
            rows = cursor.fetchall()

        return [
            {
                "telegram_id": row[0],
                "username": row[1],
                "role": row[2],
                "status": row[3],
            }
            for row in rows
        ]

    def count_admins(self):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COUNT(1) FROM telegram_users WHERE role = 'ADMIN' AND status = 'ACTIVE'"
            )
            return int(cursor.fetchone()[0])

    def list_authorized_chat_ids(self):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT telegram_id FROM telegram_users WHERE status = 'ACTIVE' ORDER BY created_at ASC"
            )
            rows = cursor.fetchall()

        return [int(row[0]) for row in rows]

    def set_session_state(self, telegram_id, state):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO auth_sessions (telegram_id, state)
                VALUES (?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (telegram_id, state),
            )

    def get_session_state(self, telegram_id):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT state FROM auth_sessions WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = cursor.fetchone()

        return row[0] if row else None

    def clear_session(self, telegram_id):
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM auth_sessions WHERE telegram_id = ?", (telegram_id,))
