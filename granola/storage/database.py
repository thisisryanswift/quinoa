import sqlite3
import os
from datetime import datetime
from pathlib import Path


class Database:
    def __init__(self, db_path=None):
        if not db_path:
            # Default to ~/.local/share/granola/granola.db
            data_dir = os.path.expanduser("~/.local/share/granola")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "granola.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Create table with full schema
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    started_at TIMESTAMP,
                    ended_at TIMESTAMP,
                    duration_seconds REAL,
                    mic_path TEXT,
                    sys_path TEXT,
                    stereo_path TEXT,
                    status TEXT,
                    mic_device_id TEXT,
                    mic_device_name TEXT,
                    directory_path TEXT
                )
            """)

            # Check for missing columns (migration for existing DBs)
            cursor = conn.execute("PRAGMA table_info(recordings)")
            columns = [row[1] for row in cursor.fetchall()]

            if "ended_at" not in columns:
                conn.execute("ALTER TABLE recordings ADD COLUMN ended_at TIMESTAMP")
            if "mic_device_id" not in columns:
                conn.execute("ALTER TABLE recordings ADD COLUMN mic_device_id TEXT")
            if "mic_device_name" not in columns:
                conn.execute("ALTER TABLE recordings ADD COLUMN mic_device_name TEXT")
            if "directory_path" not in columns:
                conn.execute("ALTER TABLE recordings ADD COLUMN directory_path TEXT")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    recording_id TEXT PRIMARY KEY,
                    text TEXT,
                    summary TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY(recording_id) REFERENCES recordings(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    assignee TEXT,
                    status TEXT DEFAULT 'open',
                    FOREIGN KEY(recording_id) REFERENCES recordings(id)
                )
            """)

    def add_recording(
        self,
        rec_id,
        title,
        started_at,
        mic_path,
        sys_path,
        mic_device_id=None,
        mic_device_name=None,
        directory_path=None,
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO recordings (id, title, started_at, mic_path, sys_path, status, mic_device_id, mic_device_name, directory_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec_id,
                    title,
                    started_at,
                    str(mic_path),
                    str(sys_path),
                    "recording",
                    mic_device_id,
                    mic_device_name,
                    str(directory_path) if directory_path else None,
                ),
            )

    def update_recording_status(
        self, rec_id, status, duration=None, stereo_path=None, ended_at=None
    ):
        with sqlite3.connect(self.db_path) as conn:
            updates = ["status = ?"]
            params = [status]

            if duration is not None:
                updates.append("duration_seconds = ?")
                params.append(duration)

            if ended_at is not None:
                updates.append("ended_at = ?")
                params.append(ended_at)

            if stereo_path is not None:
                updates.append("stereo_path = ?")
                params.append(str(stereo_path))

            params.append(rec_id)

            query = f"UPDATE recordings SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)

    def update_recording_title(self, rec_id, title):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE recordings SET title = ? WHERE id = ?",
                (title, rec_id),
            )

    def save_transcript(self, rec_id, text, summary=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO transcripts (recording_id, text, summary, created_at) VALUES (?, ?, ?, ?)",
                (rec_id, text, summary, datetime.now()),
            )

    def get_recordings(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM recordings ORDER BY started_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_recording(self, rec_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_transcript(self, rec_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM transcripts WHERE recording_id = ?", (rec_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_action_items(self, rec_id, items):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM action_items WHERE recording_id = ?", (rec_id,))
            for item in items:
                conn.execute(
                    "INSERT INTO action_items (recording_id, text, assignee) VALUES (?, ?, ?)",
                    (rec_id, item.get("text"), item.get("assignee")),
                )

    def get_action_items(self, rec_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM action_items WHERE recording_id = ?", (rec_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
