import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("quinoa")


class Database:
    """SQLite database with connection pooling.

    Uses a single persistent connection per thread for better performance.
    The connection is created lazily on first use.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if not db_path:
            data_dir = os.path.expanduser("~/.local/share/quinoa")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "quinoa.db")

        self.db_path = str(db_path)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a connection for the current thread."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database operations with auto-commit."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the connection for the current thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def _init_db(self) -> None:
        with self._conn() as conn:
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
            if "folder_id" not in columns:
                conn.execute(
                    "ALTER TABLE recordings ADD COLUMN folder_id TEXT REFERENCES meeting_folders(id)"
                )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS meeting_folders (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent_id TEXT,
                    recurring_event_id TEXT,
                    created_at TIMESTAMP,
                    sort_order INTEGER DEFAULT 0,
                    FOREIGN KEY(parent_id) REFERENCES meeting_folders(id)
                )
            """)

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

            # FTS5 Search Table
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
                    recording_id UNINDEXED,
                    text,
                    summary
                )
            """)

            # Triggers to keep FTS index updated
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
                  INSERT INTO transcripts_fts(recording_id, text, summary)
                  VALUES (new.recording_id, new.text, new.summary);
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
                  DELETE FROM transcripts_fts WHERE recording_id = old.recording_id;
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
                  UPDATE transcripts_fts SET text = new.text, summary = new.summary
                  WHERE recording_id = new.recording_id;
                END;
            """)

            # Populate FTS if empty but transcripts exist (migration)
            cursor = conn.execute("SELECT count(*) FROM transcripts_fts")
            if cursor.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO transcripts_fts(recording_id, text, summary) SELECT recording_id, text, summary FROM transcripts"
                )

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

            # Calendar events for meetings-first integration
            conn.execute("""
                CREATE TABLE IF NOT EXISTS calendar_events (
                    event_id TEXT PRIMARY KEY,
                    calendar_id TEXT DEFAULT 'primary',
                    title TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    meet_link TEXT,
                    attendees TEXT,
                    organizer_email TEXT,
                    etag TEXT,
                    synced_at TIMESTAMP,
                    recording_id TEXT,
                    hidden INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    FOREIGN KEY(recording_id) REFERENCES recordings(id)
                )
            """)

            # Check for missing hidden/notes columns (migration)
            cursor = conn.execute("PRAGMA table_info(calendar_events)")
            columns = [row[1] for row in cursor.fetchall()]
            if "hidden" not in columns:
                conn.execute("ALTER TABLE calendar_events ADD COLUMN hidden INTEGER DEFAULT 0")
            if "notes" not in columns:
                conn.execute("ALTER TABLE calendar_events ADD COLUMN notes TEXT DEFAULT ''")
            if "folder_id" not in columns:
                conn.execute(
                    "ALTER TABLE calendar_events ADD COLUMN folder_id TEXT REFERENCES meeting_folders(id)"
                )
            if "recurring_event_id" not in columns:
                conn.execute("ALTER TABLE calendar_events ADD COLUMN recurring_event_id TEXT")

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_calendar_events_start
                ON calendar_events(start_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_calendar_events_recording
                ON calendar_events(recording_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_calendar_events_recurring
                ON calendar_events(recurring_event_id)
            """)

    def get_all_past_calendar_events(self) -> list[dict[str, Any]]:
        """Get all past calendar events (for history view)."""
        now = datetime.now()
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    ce.*,
                    r.id as rec_id,
                    r.title as rec_title,
                    r.duration_seconds as rec_duration,
                    r.status as rec_status
                FROM calendar_events ce
                LEFT JOIN recordings r ON ce.recording_id = r.id
                WHERE ce.start_time < ?
                  AND (ce.hidden IS NULL OR ce.hidden = 0)
                ORDER BY ce.start_time DESC
                """,
                (now,),
            )
            return [dict(row) for row in cursor.fetchall()]

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
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO transcripts
                   (recording_id, text, summary, utterances, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (rec_id, text, summary, utterances, datetime.now()),
            )

    def get_recordings(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM recordings ORDER BY started_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_recordings_in_range(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get recordings within a date range (inclusive)."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM recordings
                   WHERE started_at >= ? AND started_at <= ?
                   ORDER BY started_at DESC""",
                (start.isoformat(), end.isoformat()),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_recording(self, rec_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_transcript(self, rec_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM transcripts WHERE recording_id = ?", (rec_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def search_transcripts(self, query: str) -> list[dict[str, Any]]:
        """Search transcripts using FTS5 and title search."""
        if not query or not query.strip():
            return []

        clean_query = query.replace('"', '""')
        fts_query = f'"{clean_query}"'
        like_query = f"%{query}%"

        logger.info(f"Searching transcripts for: '{query}' (FTS: '{fts_query}')")

        with self._conn() as conn:
            conn.row_factory = sqlite3.Row

            # FTS Search
            cursor = conn.execute(
                """
                SELECT 
                    fts.recording_id,
                    snippet(transcripts_fts, 1, '<b>', '</b>', '...', 32) as text_snippet,
                    r.title,
                    r.started_at,
                    r.duration_seconds
                FROM transcripts_fts fts
                JOIN recordings r ON fts.recording_id = r.id
                WHERE transcripts_fts MATCH ?
                ORDER BY rank
                LIMIT 50
                """,
                (fts_query,),
            )
            results = {row["recording_id"]: dict(row) for row in cursor.fetchall()}
            logger.info(f"FTS found {len(results)} matches")

            # Title Search
            cursor = conn.execute(
                """
                SELECT
                    r.id as recording_id,
                    r.title,
                    r.started_at,
                    r.duration_seconds
                FROM recordings r
                WHERE r.title LIKE ?
                ORDER BY r.started_at DESC
                LIMIT 50
                """,
                (like_query,),
            )

            logger.info(f"Title search added {title_matches} unique matches")

            # Convert to list and sort
            final_list = list(results.values())
            # Basic sort by date descending
            final_list.sort(key=lambda x: x["started_at"] or "", reverse=True)

            return final_list

    def save_speaker_names(self, rec_id: str, speaker_names: str) -> None:
        """Save speaker name mappings as JSON."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE transcripts SET speaker_names = ? WHERE recording_id = ?",
                (speaker_names, rec_id),
            )

    def get_speaker_names(self, rec_id: str) -> str | None:
        """Get speaker name mappings JSON."""
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT speaker_names FROM transcripts WHERE recording_id = ?", (rec_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def update_utterances(self, rec_id: str, utterances: str) -> None:
        """Update utterances JSON (for reassigning speakers)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE transcripts SET utterances = ? WHERE recording_id = ?",
                (utterances, rec_id),
            )

    def save_action_items(self, rec_id: str, items: list[dict[str, Any]]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM action_items WHERE recording_id = ?", (rec_id,))
            for item in items:
                conn.execute(
                    "INSERT INTO action_items (recording_id, text, assignee) VALUES (?, ?, ?)",
                    (rec_id, item.get("text"), item.get("assignee")),
                )

    def get_action_items(self, rec_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM action_items WHERE recording_id = ?", (rec_id,))
            return [dict(row) for row in cursor.fetchall()]

    def save_notes(self, rec_id: str, notes: str) -> None:
        """Save notes for a recording."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE recordings SET notes = ? WHERE id = ?",
                (notes, rec_id),
            )

    def get_notes(self, rec_id: str) -> str:
        """Get notes for a recording."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT notes FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""

    def save_enhanced_notes(self, rec_id: str, enhanced_notes: str) -> None:
        """Save AI-enhanced notes for a recording."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE recordings SET enhanced_notes = ? WHERE id = ?",
                (enhanced_notes, rec_id),
            )

    def get_enhanced_notes(self, rec_id: str) -> str:
        """Get AI-enhanced notes for a recording."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT enhanced_notes FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""

    def delete_recording(self, rec_id: str) -> None:
        """Delete a recording and all related data."""
        with self._conn() as conn:
            # Unlink from calendar events first
            conn.execute(
                "UPDATE calendar_events SET recording_id = NULL WHERE recording_id = ?", (rec_id,)
            )

            conn.execute("DELETE FROM action_items WHERE recording_id = ?", (rec_id,))
            conn.execute("DELETE FROM transcripts WHERE recording_id = ?", (rec_id,))
            conn.execute("DELETE FROM file_search_sync WHERE recording_id = ?", (rec_id,))
            conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))

    # ==================== File Search Sync Methods ====================

    def get_sync_status(self, rec_id: str) -> dict[str, Any] | None:
        """Get sync status for a recording."""
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM file_search_sync WHERE sync_status = 'synced'")
            return [dict(row) for row in cursor.fetchall()]

    def mark_for_deletion(self, rec_id: str) -> None:
        """Mark a sync record for deletion from cloud."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE file_search_sync SET sync_status = 'deleted' WHERE recording_id = ?",
                (rec_id,),
            )

    def get_pending_deletions(self) -> list[dict[str, Any]]:
        """Get recordings marked for deletion from cloud."""
        with self._conn() as conn:
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
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO chat_history (session_id, role, content, citations)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, citations),
            )

    def get_chat_history(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get chat history for a session."""
        with self._conn() as conn:
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
        with self._conn() as conn:
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))

    # ==================== Calendar Events Methods ====================

    def upsert_calendar_events(self, events: list[dict[str, Any]]) -> int:
        """Insert or update calendar events. Returns number of rows changed."""
        total_changes = 0
        with self._conn() as conn:
            for event in events:
                conn.execute(
                    """
                    INSERT INTO calendar_events
                        (event_id, calendar_id, title, start_time, end_time,
                         meet_link, attendees, organizer_email, etag, synced_at, recurring_event_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        calendar_id = excluded.calendar_id,
                        title = excluded.title,
                        start_time = excluded.start_time,
                        end_time = excluded.end_time,
                        meet_link = excluded.meet_link,
                        attendees = excluded.attendees,
                        organizer_email = excluded.organizer_email,
                        etag = excluded.etag,
                        synced_at = excluded.synced_at,
                        recurring_event_id = excluded.recurring_event_id,
                        hidden = COALESCE(calendar_events.hidden, 0)
                    """,
                    (
                        event["event_id"],
                        event.get("calendar_id", "primary"),
                        event["title"],
                        event["start_time"],
                        event["end_time"],
                        event.get("meet_link"),
                        event.get("attendees"),  # JSON string
                        event.get("organizer_email"),
                        event.get("etag"),
                        datetime.now(),
                        event.get("recurring_event_id"),
                    ),
                )
                total_changes += conn.total_changes
        return total_changes

    def save_calendar_event_notes(self, event_id: str, notes: str) -> None:
        """Save notes for a calendar event."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE calendar_events SET notes = ? WHERE event_id = ?",
                (notes, event_id),
            )

    def get_calendar_event_notes(self, event_id: str) -> str:
        """Get notes for a calendar event."""
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT notes FROM calendar_events WHERE event_id = ?", (event_id,)
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""

    def get_calendar_events(self, start_date: datetime, end_date: datetime) -> list[dict[str, Any]]:
        """Get calendar events in a date range with recording info."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    ce.*,
                    r.id as rec_id,
                    r.title as rec_title,
                    r.duration_seconds as rec_duration,
                    r.status as rec_status
                FROM calendar_events ce
                LEFT JOIN recordings r ON ce.recording_id = r.id
                WHERE ce.start_time >= ? AND ce.start_time < ?
                  AND (ce.hidden IS NULL OR ce.hidden = 0)
                ORDER BY ce.start_time ASC
                """,
                (start_date, end_date),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_todays_calendar_events(self) -> list[dict[str, Any]]:
        """Get today's calendar events with recording info."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)
        return self.get_calendar_events(today_start, today_end)

    def set_calendar_event_hidden(self, event_id: str, hidden: bool = True) -> None:
        """Set the hidden status of a calendar event."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE calendar_events SET hidden = ? WHERE event_id = ?",
                (1 if hidden else 0, event_id),
            )

    def get_current_meeting(self, buffer_minutes: int = 10) -> dict[str, Any] | None:
        """Find a meeting happening now (within buffer window)."""

        now = datetime.now()
        window_start = now - timedelta(minutes=buffer_minutes)
        window_end = now + timedelta(minutes=buffer_minutes)

        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM calendar_events
                WHERE (start_time <= ? AND end_time >= ?
                   OR (start_time >= ? AND start_time <= ?))
                   AND (hidden IS NULL OR hidden = 0)
                ORDER BY start_time ASC
                LIMIT 1
                """,
                (now, now, window_start, window_end),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def link_recording_to_event(self, event_id: str, recording_id: str) -> None:
        """Link a recording to a calendar event."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE calendar_events SET recording_id = ? WHERE event_id = ?",
                (recording_id, event_id),
            )

    def get_calendar_event(self, event_id: str) -> dict[str, Any] | None:
        """Get a single calendar event by ID."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    ce.*,
                    r.id as rec_id,
                    r.title as rec_title,
                    r.duration_seconds as rec_duration,
                    r.status as rec_status
                FROM calendar_events ce
                LEFT JOIN recordings r ON ce.recording_id = r.id
                WHERE ce.event_id = ?
                """,
                (event_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def clear_calendar_events(self) -> None:
        """Clear all calendar events (for re-sync or logout)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM calendar_events")

    # ==================== Folder Management Methods ====================

    def create_folder(
        self,
        folder_id: str,
        name: str,
        parent_id: str | None = None,
        recurring_event_id: str | None = None,
        sort_order: int = 0,
    ) -> None:
        """Create a new meeting folder."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO meeting_folders
                (id, name, parent_id, recurring_event_id, created_at, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    folder_id,
                    name,
                    parent_id,
                    recurring_event_id,
                    datetime.now(),
                    sort_order,
                ),
            )

    def update_folder(
        self,
        folder_id: str,
        name: str | None = None,
        parent_id: str | None = None,
        sort_order: int | None = None,
    ) -> None:
        """Update a meeting folder."""
        with self._conn() as conn:
            updates = []
            params: list[Any] = []

            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if parent_id is not None:
                updates.append("parent_id = ?")
                params.append(parent_id)
            if sort_order is not None:
                updates.append("sort_order = ?")
                params.append(sort_order)

            if not updates:
                return

            params.append(folder_id)
            conn.execute(
                f"UPDATE meeting_folders SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def delete_folder(self, folder_id: str) -> None:
        """Delete a folder.

        Items in the folder will have their folder_id set to NULL (Uncategorized).
        Subfolders will have their parent_id set to NULL (become top-level).
        """
        with self._conn() as conn:
            # Unlink subfolders
            conn.execute(
                "UPDATE meeting_folders SET parent_id = NULL WHERE parent_id = ?", (folder_id,)
            )
            # Unlink recordings
            conn.execute("UPDATE recordings SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
            # Unlink calendar events
            conn.execute(
                "UPDATE calendar_events SET folder_id = NULL WHERE folder_id = ?", (folder_id,)
            )
            # Delete the folder
            conn.execute("DELETE FROM meeting_folders WHERE id = ?", (folder_id,))

    def get_folder_by_recurring_id(self, recurring_id: str) -> dict[str, Any] | None:
        """Find a folder linked to a recurring event series."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM meeting_folders WHERE recurring_event_id = ?", (recurring_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_folders(self) -> list[dict[str, Any]]:
        """Get all folders ordered by sort_order and name."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM meeting_folders ORDER BY sort_order ASC, name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def set_recording_folder(self, rec_id: str, folder_id: str | None) -> None:
        """Move a recording to a folder."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE recordings SET folder_id = ? WHERE id = ?",
                (folder_id, rec_id),
            )

    def set_calendar_event_folder(self, event_id: str, folder_id: str | None) -> None:
        """Move a calendar event to a folder."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE calendar_events SET folder_id = ? WHERE event_id = ?",
                (folder_id, event_id),
            )
