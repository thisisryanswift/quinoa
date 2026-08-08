"""Regression tests for database sync state handling."""

import tempfile
from datetime import datetime
from typing import cast

import pytest

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
