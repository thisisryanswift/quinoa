"""Regression tests for database sync state handling and UTC migration."""

import os
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from quinoa.datetime_utils import (
    to_local_date_key,
    to_local_naive,
)
from quinoa.storage.database import Database


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        database = Database(tmp.name)
    yield database


def _add_recording(database, rec_id, duration=60):
    database.add_recording(
        rec_id=rec_id,
        title="Test",
        started_at=datetime.now(),
        mic_path="/tmp/mic.wav",
        sys_path="/tmp/sys.wav",
        directory_path="/tmp",
    )
    database.update_recording_status(rec_id, status="completed", duration=duration)


def test_get_unsynced_recordings_includes_pending_status(db):
    """Recordings with status 'pending' must be returned by the backfill query."""
    rec_id = "rec-pending"
    _add_recording(db, rec_id)
    db.save_transcript(rec_id, "text", "summary", None)
    db.set_sync_status(rec_id, "pending")

    unsynced = db.get_unsynced_recordings(min_duration_seconds=30)
    ids = {r["id"] for r in unsynced}
    assert rec_id in ids


def test_get_unsynced_recordings_excludes_synced_status(db):
    rec_id = "rec-synced"
    _add_recording(db, rec_id)
    db.save_transcript(rec_id, "text", "summary", None)
    db.set_sync_status(rec_id, "synced")

    unsynced = db.get_unsynced_recordings(min_duration_seconds=30)
    ids = {r["id"] for r in unsynced}
    assert rec_id not in ids


def test_set_sync_status_pending_sets_no_last_synced_at(db):
    rec_id = "rec-status"
    _add_recording(db, rec_id)
    db.set_sync_status(rec_id, "pending")

    status = db.get_sync_status(rec_id)
    assert status["sync_status"] == "pending"
    assert status["last_synced_at"] is None


def test_save_transcript_preserves_speaker_names(db):
    """Re-saving a transcript must not wipe speaker name mappings."""
    rec_id = "rec-speakers"
    _add_recording(db, rec_id)

    db.save_transcript(rec_id, "first draft", "summary", None)
    db.save_speaker_names(rec_id, '{"Speaker 1": "Alice"}')

    db.save_transcript(rec_id, "second draft", "new summary", "[]")

    transcript = db.get_transcript(rec_id)
    assert transcript["text"] == "second draft"
    assert transcript["summary"] == "new summary"
    assert transcript["speaker_names"] == '{"Speaker 1": "Alice"}'


def test_delete_recording_preserves_sync_row_for_cloud_cleanup():
    """Deleting a synced recording must leave a 'deleted' sync row for the worker."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        database = Database(tmp.name)
    rec_id = "rec-delete-synced"
    _add_recording(database, rec_id)
    database.save_transcript(rec_id, "text", "summary", None)
    database.set_sync_status(rec_id, "synced", file_name="stores/foo/documents/1")

    database.delete_recording(rec_id)

    assert database.get_recording(rec_id) is None
    status = database.get_sync_status(rec_id)
    assert status is not None
    assert status["sync_status"] == "deleted"
    assert status["file_search_file_name"] == "stores/foo/documents/1"


def test_delete_recording_removes_stale_sync_row():
    """Deleting an unsynced recording should not leave an orphan sync row."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        database = Database(tmp.name)
    rec_id = "rec-delete-unsynced"
    _add_recording(database, rec_id)
    database.save_transcript(rec_id, "text", "summary", None)
    database.set_sync_status(rec_id, "pending")

    database.delete_recording(rec_id)

    assert database.get_recording(rec_id) is None
    assert database.get_sync_status(rec_id) is None


def test_get_unsynced_recordings_includes_transcribed_status(db):
    """Backfill after restart must include recordings already marked transcribed."""
    rec_id = "rec-transcribed"
    _add_recording(db, rec_id)
    db.update_recording_status(rec_id, status="transcribed", duration=60)
    db.save_transcript(rec_id, "text", "summary", None)
    db.set_sync_status(rec_id, "pending")

    unsynced = db.get_unsynced_recordings(min_duration_seconds=30)
    ids = {r["id"] for r in unsynced}
    assert rec_id in ids


def test_get_unsynced_recordings_excludes_deleted_status(db):
    """Recordings marked for cloud deletion must not be re-queued for upload."""
    rec_id = "rec-deleted"
    _add_recording(db, rec_id)
    db.save_transcript(rec_id, "text", "summary", None)
    db.set_sync_status(rec_id, "deleted")

    unsynced = db.get_unsynced_recordings(min_duration_seconds=30)
    ids = {r["id"] for r in unsynced}
    assert rec_id not in ids


def test_queue_sync_after_transcription_persists_without_sync_worker(db, monkeypatch):
    """A finished transcription must be marked pending even when File Search has no worker."""
    from quinoa.ui import main_window as mw

    class FakeConfig:
        @staticmethod
        def get(key: str, default=None):
            return True if key == "file_search_enabled" else default

    monkeypatch.setattr(mw, "config", FakeConfig())

    class FakeWindow:
        def __init__(self, database):
            self.db = database
            self._sync_worker = None

    _add_recording(db, "rec-persist")
    mw.MainWindow._queue_sync_after_transcription(
        cast(mw.MainWindow, FakeWindow(db)), "rec-persist", ""
    )

    status = db.get_sync_status("rec-persist")
    assert status is not None
    assert status["sync_status"] == "pending"


# -----------------------------------------------------------------------------
# Canonical UTC timestamp migration and serialization tests
# -----------------------------------------------------------------------------


def _legacy_schema(conn: sqlite3.Connection) -> None:
    """Create a schema representative of a pre-migration database."""
    conn.execute("""
        CREATE TABLE recordings (
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
    conn.execute("""
        CREATE TABLE meeting_folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT,
            recurring_event_id TEXT,
            created_at TIMESTAMP,
            sort_order INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE speaker_profiles (
            name TEXT PRIMARY KEY,
            usage_count INTEGER DEFAULT 1,
            last_used_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE transcripts (
            recording_id TEXT PRIMARY KEY,
            text TEXT,
            summary TEXT,
            utterances TEXT,
            speaker_names TEXT,
            created_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE file_search_sync (
            recording_id TEXT PRIMARY KEY,
            file_search_file_name TEXT,
            last_synced_at TIMESTAMP,
            content_hash TEXT,
            sync_status TEXT DEFAULT 'pending',
            error_message TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE calendar_events (
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
            notes TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            citations TEXT
        )
    """)


def _insert_legacy_data(conn: sqlite3.Connection) -> None:
    """Insert representative legacy timestamp values across all migrated columns."""
    # New York naive summer and winter wall times
    conn.execute(
        "INSERT INTO recordings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rec-1",
            "Summer",
            "2026-08-08 18:07:12.123456",
            "2026-08-08 19:07:12",
            None,
            "/tmp/mic.wav",
            "/tmp/sys.wav",
            None,
            "completed",
            None,
            None,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO recordings(id, title, started_at) VALUES (?, ?, ?)",
        ("rec-2", "Winter", "2026-01-08 18:07:12"),
    )
    # Aware offset value
    conn.execute(
        "INSERT INTO calendar_events(event_id, title, start_time, end_time, synced_at) VALUES (?, ?, ?, ?, ?)",
        (
            "evt-1",
            "Aware",
            "2026-08-08T18:07:12-04:00",
            "2026-08-08T19:07:12-04:00",
            "2026-08-08T22:00:00+00:00",
        ),
    )
    # Chat naive UTC
    conn.execute(
        "INSERT INTO chat_history(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("s1", "user", "hi", "2026-08-08 22:07:12"),
    )
    # Remaining columns
    conn.execute(
        "INSERT INTO meeting_folders(id, name, created_at) VALUES (?, ?, ?)",
        ("folder-1", "Series", "2026-08-08 18:00:00"),
    )
    conn.execute(
        "INSERT INTO speaker_profiles(name, last_used_at) VALUES (?, ?)",
        ("Alice", "2026-08-08 18:00:00"),
    )
    conn.execute(
        "INSERT INTO transcripts(recording_id, text, created_at) VALUES (?, ?, ?)",
        ("rec-1", "text", "2026-08-08 18:00:00"),
    )
    conn.execute(
        "INSERT INTO file_search_sync(recording_id, sync_status, last_synced_at) VALUES (?, ?, ?)",
        ("rec-1", "synced", "2026-08-08 18:00:00"),
    )


def test_migration_canonicalizes_all_columns_and_sets_user_version():
    """Every legacy timestamp column migrates to fixed-width UTC ISO text."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    _insert_legacy_data(conn)
    conn.commit()
    conn.close()

    try:
        Database(path)

        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

        def value(table: str, column: str, where: str) -> Any:
            return conn.execute(f"SELECT {column} FROM {table} WHERE {where}").fetchone()[0]

        # New York summer -> UTC
        assert value("recordings", "started_at", "id='rec-1'") == "2026-08-08T22:07:12.123456+00:00"
        assert value("recordings", "ended_at", "id='rec-1'") == "2026-08-08T23:07:12.000000+00:00"
        # New York winter -> UTC
        assert value("recordings", "started_at", "id='rec-2'") == "2026-01-08T23:07:12.000000+00:00"
        # Aware offset -> UTC
        assert (
            value("calendar_events", "start_time", "event_id='evt-1'")
            == "2026-08-08T22:07:12.000000+00:00"
        )
        # Chat naive UTC -> UTC
        assert value("chat_history", "timestamp", "id=1") == "2026-08-08T22:07:12.000000+00:00"
        assert (
            value("meeting_folders", "created_at", "id='folder-1'")
            == "2026-08-08T22:00:00.000000+00:00"
        )
        assert (
            value("speaker_profiles", "last_used_at", "name='Alice'")
            == "2026-08-08T22:00:00.000000+00:00"
        )
        assert (
            value("transcripts", "created_at", "recording_id='rec-1'")
            == "2026-08-08T22:00:00.000000+00:00"
        )
        assert (
            value("file_search_sync", "last_synced_at", "recording_id='rec-1'")
            == "2026-08-08T22:00:00.000000+00:00"
        )

        backup_path = path + ".pre-utc-v1.bak"
        assert os.path.exists(backup_path)
        backup_conn = sqlite3.connect(backup_path)
        assert backup_conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            backup_conn.execute("SELECT started_at FROM recordings WHERE id='rec-1'").fetchone()[0]
            == "2026-08-08 18:07:12.123456"
        )
        backup_conn.close()

        conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_migration_is_idempotent():
    """PRAGMA user_version ensures migration runs only once."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    _insert_legacy_data(conn)
    conn.commit()
    conn.close()

    try:
        Database(path)

        conn = sqlite3.connect(path)
        first_started = conn.execute(
            "SELECT started_at FROM recordings WHERE id='rec-1'"
        ).fetchone()[0]
        conn.close()

        # Re-opening should not change anything and should not create a second backup.
        Database(path)
        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            conn.execute("SELECT started_at FROM recordings WHERE id='rec-1'").fetchone()[0]
            == first_started
        )
        conn.close()

        # Re-opening a migrated database must not create an additional backup.
        assert os.path.exists(path + ".pre-utc-v1.bak")
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_migration_refuses_pre_existing_backup():
    """A pre-existing backup blocks migration to avoid overwrite."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    backup = path + ".pre-utc-v1.bak"

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    _insert_legacy_data(conn)
    conn.commit()
    conn.close()

    # Create the backup file beforehand.
    Path(backup).write_text("existing backup")

    try:
        with pytest.raises(ValueError, match="backup.*already exists"):
            Database(path)

        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        # Source rows unchanged.
        assert (
            conn.execute("SELECT started_at FROM recordings WHERE id='rec-1'").fetchone()[0]
            == "2026-08-08 18:07:12.123456"
        )
        conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
        if os.path.exists(backup):
            os.unlink(backup)


def test_migration_aborts_on_malformed_timestamp():
    """Malformed timestamp rolls back with table/column/key context."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    conn.execute(
        "INSERT INTO recordings(id, title, started_at) VALUES (?, ?, ?)",
        ("rec-malformed", "Malformed", "not-a-timestamp"),
    )
    conn.commit()
    conn.close()

    try:
        with pytest.raises(ValueError, match="recordings.started_at@rec-malformed.*malformed"):
            Database(path)

        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            conn.execute("SELECT started_at FROM recordings WHERE id='rec-malformed'").fetchone()[0]
            == "not-a-timestamp"
        )
        conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_migration_aborts_on_spring_forward():
    """Nonexistent spring-forward wall time rolls back with table/column/key context."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    conn.execute(
        "INSERT INTO recordings(id, title, started_at) VALUES (?, ?, ?)",
        ("rec-bad", "Bad", "2026-03-08 02:30:00"),
    )
    conn.commit()
    conn.close()

    try:
        with pytest.raises(ValueError, match="recordings.started_at@rec-bad"):
            Database(path)

        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            conn.execute("SELECT started_at FROM recordings WHERE id='rec-bad'").fetchone()[0]
            == "2026-03-08 02:30:00"
        )
        conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_migration_aborts_on_ambiguous_fallback():
    """Ambiguous fall-back wall time rolls back with table/column/key context."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    conn.execute(
        "INSERT INTO recordings(id, title, started_at) VALUES (?, ?, ?)",
        ("rec-ambig", "Ambig", "2026-11-01 01:30:00"),
    )
    conn.commit()
    conn.close()

    try:
        with pytest.raises(ValueError, match="recordings.started_at@rec-ambig"):
            Database(path)

        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_empty_database_sets_version_without_backup():
    """New/empty file databases set user_version=1 without creating a backup."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    try:
        Database(path)
        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        conn.close()
        assert not os.path.exists(path + ".pre-utc-v1.bak")
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_in_memory_database_sets_version_and_persists_schema():
    """In-memory databases migrate to version 1 and keep schema after init closes."""
    db = Database(":memory:")

    # Schema must persist so we can write.
    db.add_recording(
        "rec-mem",
        "Memory",
        datetime(2026, 8, 8, 22, 0, 0, tzinfo=UTC),
        "/tmp/mic.wav",
        "/tmp/sys.wav",
    )
    rec = db.get_recording("rec-mem")
    assert rec is not None
    assert rec["started_at"] == "2026-08-08T22:00:00.000000+00:00"


def test_in_memory_database_instances_are_isolated():
    first = Database(":memory:")
    second = Database(":memory:")
    first.add_recording(
        "rec-first",
        "First",
        datetime(2026, 8, 8, 22, 0, tzinfo=UTC),
        "/tmp/mic.wav",
        "/tmp/sys.wav",
    )

    assert first.get_recording("rec-first") is not None
    assert second.get_recording("rec-first") is None


def test_concurrent_initialization_serializes():
    """Threads racing to initialize the same database serialize safely."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    conn = sqlite3.connect(path)
    _legacy_schema(conn)
    _insert_legacy_data(conn)
    conn.commit()
    conn.close()

    errors: list[Exception | None] = [None, None]
    dbs: list[Database | None] = [None, None]

    def init_db(index: int) -> None:
        try:
            dbs[index] = Database(path)
        except Exception as exc:
            errors[index] = exc

    threads = [threading.Thread(target=init_db, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert all(e is None for e in errors), errors
        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 2
        conn.close()
        assert os.path.exists(path + ".pre-utc-v1.bak")
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_query_bounds_are_canonical_utc():
    """Range queries find recordings using canonical UTC bounds."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    db = Database(path)
    try:
        # 2026-08-08 18:00 New York summer = 22:00 UTC
        nyc_wall = datetime(2026, 8, 8, 18, 0, 0)
        utc_instant = nyc_wall.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
        db.add_recording("rec-range", "Range", utc_instant, "/tmp/mic.wav", "/tmp/sys.wav")

        # Query by naive New York day bounds should find the recording.
        start = nyc_wall.replace(hour=0, minute=0, second=0, microsecond=0)
        end = nyc_wall.replace(hour=23, minute=59, second=59)
        results = db.get_recordings_in_range(start, end)
        assert any(r["id"] == "rec-range" for r in results)

        winter_wall = datetime(2026, 1, 8, 18, 0, 0)
        winter_utc = winter_wall.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
        db.add_recording("rec-winter", "Winter", winter_utc, "/tmp/mic.wav", "/tmp/sys.wav")
        winter_results = db.get_recordings_in_range(
            winter_wall.replace(hour=0, minute=0, second=0, microsecond=0),
            winter_wall.replace(hour=23, minute=59, second=59),
        )
        assert any(r["id"] == "rec-winter" for r in winter_results)
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_chat_message_writes_explicit_utc_timestamp():
    """save_chat_message binds an explicit aware UTC timestamp."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    db = Database(path)
    try:
        db.save_chat_message("session-1", "user", "hello")
        messages = db.get_chat_history("session-1")
        assert len(messages) == 1
        ts = messages[0]["timestamp"]
        assert ts.endswith("+00:00")
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)


def test_local_date_key_avoids_utc_boundary_regression():
    """A UTC instant on the next local day maps back to the correct local date key."""
    # 2026-08-09 06:30 UTC is 2026-08-08 in the Americas.
    utc_str = "2026-08-09T06:30:00.000000+00:00"
    local_naive = to_local_naive(utc_str)
    assert local_naive.tzinfo is None
    date_key = to_local_date_key(utc_str)
    assert date_key.startswith("2026-08-")


def test_recordings_and_calendar_events_use_canonical_aware_timestamps():
    """New writes produce fixed-width UTC ISO strings."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    db = Database(path)
    try:
        utc = datetime(2026, 8, 8, 22, 0, 0, tzinfo=UTC)
        db.add_recording("rec-new", "New", utc, "/tmp/mic.wav", "/tmp/sys.wav")
        db.upsert_calendar_events(
            [
                {
                    "event_id": "evt-new",
                    "title": "New",
                    "start_time": utc,
                    "end_time": utc,
                }
            ]
        )

        conn = sqlite3.connect(path)
        rec_ts = conn.execute("SELECT started_at FROM recordings WHERE id='rec-new'").fetchone()[0]
        evt_ts = conn.execute(
            "SELECT start_time FROM calendar_events WHERE event_id='evt-new'"
        ).fetchone()[0]
        assert rec_ts == "2026-08-08T22:00:00.000000+00:00"
        assert evt_ts == "2026-08-08T22:00:00.000000+00:00"
        conn.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
        backup = path + ".pre-utc-v1.bak"
        if os.path.exists(backup):
            os.unlink(backup)
