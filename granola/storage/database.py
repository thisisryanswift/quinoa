import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if not db_path:
            # Default to ~/.local/share/granola/granola.db
            data_dir = os.path.expanduser("~/.local/share/granola")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "granola.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
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
            if "notes" not in columns:
                conn.execute("ALTER TABLE recordings ADD COLUMN notes TEXT DEFAULT ''")
            if "enhanced_notes" not in columns:
                conn.execute("ALTER TABLE recordings ADD COLUMN enhanced_notes TEXT")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    recording_id TEXT PRIMARY KEY,
                    text TEXT,
                    summary TEXT,
                    utterances TEXT,
                    speaker_names TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY(recording_id) REFERENCES recordings(id)
                )
            """)

            # Migration for existing transcripts table
            cursor = conn.execute("PRAGMA table_info(transcripts)")
            transcript_columns = [row[1] for row in cursor.fetchall()]
            if "utterances" not in transcript_columns:
                conn.execute("ALTER TABLE transcripts ADD COLUMN utterances TEXT")
            if "speaker_names" not in transcript_columns:
                conn.execute("ALTER TABLE transcripts ADD COLUMN speaker_names TEXT")
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

            # File Search sync tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_search_sync (
                    recording_id TEXT PRIMARY KEY,
                    file_search_file_name TEXT,
                    last_synced_at TIMESTAMP,
                    content_hash TEXT,
                    sync_status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    FOREIGN KEY(recording_id) REFERENCES recordings(id)
                )
            """)

            # Chat history for AI assistant
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    citations TEXT
                )
            """)

    def add_recording(
        self,
        rec_id: str,
        title: str,
        started_at: datetime,
        mic_path: str | Path,
        sys_path: str | Path,
        mic_device_id: str | None = None,
        mic_device_name: str | None = None,
        directory_path: str | Path | None = None,
    ) -> None:
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
        self,
        rec_id: str,
        status: str,
        duration: float | None = None,
        stereo_path: str | Path | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            updates = ["status = ?"]
            params: list[Any] = [status]

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

    def update_recording_title(self, rec_id: str, title: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE recordings SET title = ? WHERE id = ?",
                (title, rec_id),
            )

    def save_transcript(
        self,
        rec_id: str,
        text: str,
        summary: str | None = None,
        utterances: str | None = None,
    ) -> None:
        """Save transcript with optional utterances JSON."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO transcripts
                   (recording_id, text, summary, utterances, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (rec_id, text, summary, utterances, datetime.now()),
            )

    def get_recordings(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM recordings ORDER BY started_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_recording(self, rec_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_transcript(self, rec_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM transcripts WHERE recording_id = ?", (rec_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_speaker_names(self, rec_id: str, speaker_names: str) -> None:
        """Save speaker name mappings as JSON."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE transcripts SET speaker_names = ? WHERE recording_id = ?",
                (speaker_names, rec_id),
            )

    def get_speaker_names(self, rec_id: str) -> str | None:
        """Get speaker name mappings JSON."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT speaker_names FROM transcripts WHERE recording_id = ?", (rec_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def update_utterances(self, rec_id: str, utterances: str) -> None:
        """Update utterances JSON (for reassigning speakers)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE transcripts SET utterances = ? WHERE recording_id = ?",
                (utterances, rec_id),
            )

    def save_action_items(self, rec_id: str, items: list[dict[str, Any]]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM action_items WHERE recording_id = ?", (rec_id,))
            for item in items:
                conn.execute(
                    "INSERT INTO action_items (recording_id, text, assignee) VALUES (?, ?, ?)",
                    (rec_id, item.get("text"), item.get("assignee")),
                )

    def get_action_items(self, rec_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM action_items WHERE recording_id = ?", (rec_id,))
            return [dict(row) for row in cursor.fetchall()]

    def save_notes(self, rec_id: str, notes: str) -> None:
        """Save notes for a recording."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE recordings SET notes = ? WHERE id = ?",
                (notes, rec_id),
            )

    def get_notes(self, rec_id: str) -> str:
        """Get notes for a recording."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT notes FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""

    def save_enhanced_notes(self, rec_id: str, enhanced_notes: str) -> None:
        """Save AI-enhanced notes for a recording."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE recordings SET enhanced_notes = ? WHERE id = ?",
                (enhanced_notes, rec_id),
            )

    def get_enhanced_notes(self, rec_id: str) -> str:
        """Get AI-enhanced notes for a recording."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT enhanced_notes FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""

    def delete_recording(self, rec_id: str) -> None:
        """Delete a recording and all related data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM action_items WHERE recording_id = ?", (rec_id,))
            conn.execute("DELETE FROM transcripts WHERE recording_id = ?", (rec_id,))
            conn.execute("DELETE FROM file_search_sync WHERE recording_id = ?", (rec_id,))
            conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))

    # ==================== File Search Sync Methods ====================

    def get_sync_status(self, rec_id: str) -> dict[str, Any] | None:
        """Get sync status for a recording."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM file_search_sync WHERE recording_id = ?", (rec_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_sync_status(
        self,
        rec_id: str,
        status: str,
        file_name: str | None = None,
        content_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update sync status for a recording."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO file_search_sync
                    (recording_id, sync_status, file_search_file_name, content_hash,
                     error_message, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(recording_id) DO UPDATE SET
                    sync_status = excluded.sync_status,
                    file_search_file_name = COALESCE(excluded.file_search_file_name, file_search_file_name),
                    content_hash = COALESCE(excluded.content_hash, content_hash),
                    error_message = excluded.error_message,
                    last_synced_at = excluded.last_synced_at
                """,
                (
                    rec_id,
                    status,
                    file_name,
                    content_hash,
                    error,
                    datetime.now() if status == "synced" else None,
                ),
            )

    def get_unsynced_recordings(self, min_duration_seconds: float = 30) -> list[dict[str, Any]]:
        """Get recordings that need syncing (have transcripts, long enough, not synced)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT r.* FROM recordings r
                INNER JOIN transcripts t ON r.id = t.recording_id
                LEFT JOIN file_search_sync s ON r.id = s.recording_id
                WHERE r.status = 'completed'
                  AND r.duration_seconds >= ?
                  AND (s.sync_status IS NULL OR s.sync_status NOT IN ('synced', 'pending'))
                ORDER BY r.started_at DESC
                """,
                (min_duration_seconds,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_synced_recordings(self) -> list[dict[str, Any]]:
        """Get all synced recording IDs and file names."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM file_search_sync WHERE sync_status = 'synced'")
            return [dict(row) for row in cursor.fetchall()]

    def mark_for_deletion(self, rec_id: str) -> None:
        """Mark a sync record for deletion from cloud."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE file_search_sync SET sync_status = 'deleted' WHERE recording_id = ?",
                (rec_id,),
            )

    def get_pending_deletions(self) -> list[dict[str, Any]]:
        """Get recordings marked for deletion from cloud."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM file_search_sync WHERE sync_status = 'deleted'")
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Chat History Methods ====================

    def save_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: str | None = None,
    ) -> None:
        """Save a chat message."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO chat_history (session_id, role, content, citations)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, citations),
            )

    def get_chat_history(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get chat history for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM chat_history
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (session_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def clear_chat_history(self, session_id: str) -> None:
        """Clear chat history for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
