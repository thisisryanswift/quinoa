"""Regression tests for File Search sync worker behavior."""

import tempfile
from datetime import datetime
from unittest.mock import MagicMock

from quinoa.search.file_search import FileSearchManager
from quinoa.search.sync_worker import SyncWorker


def test_sync_recording_uploads_before_deleting_old_document():
    """Old document must only be deleted after the new upload succeeds."""
    db = MagicMock()
    db.get_recording.return_value = {
        "id": "rec-1",
        "duration_seconds": 60,
        "started_at": datetime.now(),
    }
    db.get_transcript.return_value = {"text": "transcript"}
    db.get_notes.return_value = "notes"
    db.get_action_items.return_value = []
    db.get_event_for_recording.return_value = None
    db.get_folder.return_value = None
    db.get_sync_status.return_value = {
        "file_search_file_name": "old-doc",
        "content_hash": "old-hash",
    }

    file_search = MagicMock(spec=FileSearchManager)
    file_search.upload_meeting.return_value = "new-doc"

    worker = SyncWorker(db, file_search)

    deleted_during_upload = []

    def capture_delete(doc_name):
        deleted_during_upload.append(
            (doc_name, db.set_sync_status.call_args.kwargs.get("file_name"))
        )
        return True

    file_search.delete_meeting.side_effect = capture_delete
    worker._sync_recording("rec-1")

    assert file_search.upload_meeting.called
    assert ("old-doc", "new-doc") in deleted_during_upload
    assert db.set_sync_status.call_args.args == ("rec-1", "synced")
    assert db.set_sync_status.call_args.kwargs.get("file_name") == "new-doc"
    assert db.set_sync_status.call_args.kwargs.get("content_hash") is not None


def test_upload_meeting_always_deletes_temp_file(monkeypatch):
    """upload_meeting must clean up the exact temporary file it created."""
    import os

    from quinoa.search import file_search as fs_mod

    real_ntf = tempfile.NamedTemporaryFile
    captured_paths: list[str] = []

    def capturing_ntf(*args, **kwargs):
        tmp = real_ntf(*args, **kwargs)
        captured_paths.append(tmp.name)
        return tmp

    monkeypatch.setattr(fs_mod.tempfile, "NamedTemporaryFile", capturing_ntf)

    manager = FileSearchManager(api_key="test-key")
    manager.client = MagicMock()
    operation = MagicMock()
    operation.done = True
    operation.response.document_name = "doc-1"
    manager.client.file_search_stores.upload_to_file_search_store.return_value = operation

    manager._store_name = "stores/test"

    file_name = manager.upload_meeting("rec-1", "meeting content", "2024-01-01")

    assert file_name == "doc-1"
    assert len(captured_paths) == 1
    # The actual NamedTemporaryFile path must be deleted, not just absent by accident.
    assert not os.path.exists(captured_paths[0])
