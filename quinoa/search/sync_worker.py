"""Background worker for syncing meetings to Gemini File Search."""

import logging
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QThread, pyqtSignal

from quinoa.constants import FILE_SEARCH_POLL_INTERVAL_MS, MIN_SYNC_DURATION_SECONDS
from quinoa.search.content_formatter import compute_content_hash, format_meeting_document
from quinoa.search.file_search import FileSearchError, FileSearchManager

if TYPE_CHECKING:
    from quinoa.storage.database import Database

logger = logging.getLogger("quinoa")


class SyncWorker(QThread):
    """Background worker for syncing meetings to File Search."""

    sync_completed = pyqtSignal(str)  # recording_id
    sync_failed = pyqtSignal(str, str)  # recording_id, error
    sync_progress = pyqtSignal(int, int)  # current, total
    store_ready = pyqtSignal(str)  # store_name

    def __init__(
        self,
        db: "Database",
        file_search: FileSearchManager,
        poll_interval_ms: int = FILE_SEARCH_POLL_INTERVAL_MS,
    ):
        super().__init__()
        self.db = db
        self.file_search = file_search
        self.poll_interval_ms = poll_interval_ms
        self._running = True
        self._pending_queue: list[tuple[str, float]] = []  # (rec_id, eligible_time)

    def queue_for_sync(self, rec_id: str, delay_seconds: int = 300) -> None:
        """Queue a recording for delayed sync.

        Args:
            rec_id: Recording ID to sync
            delay_seconds: Seconds to wait before syncing (default 5 min)
        """
        eligible_time = time.time() + delay_seconds
        # Remove any existing entry for this recording
        self._pending_queue = [(rid, t) for rid, t in self._pending_queue if rid != rec_id]
        self._pending_queue.append((rec_id, eligible_time))
        logger.debug("Queued %s for sync in %d seconds", rec_id, delay_seconds)

    def queue_all_unsynced(self) -> None:
        """Queue all unsynced recordings for immediate sync (backfill)."""
        unsynced = self.db.get_unsynced_recordings(MIN_SYNC_DURATION_SECONDS)
        for recording in unsynced:
            rec_id = recording["id"]
            # Queue with no delay for backfill
            self._pending_queue.append((rec_id, time.time()))
        logger.info("Queued %d recordings for backfill sync", len(unsynced))

    def run(self) -> None:
        """Main sync loop."""
        # Initialize store
        try:
            store_name = self.file_search.ensure_store_exists()
            self.store_ready.emit(store_name)
        except FileSearchError as e:
            logger.error("Failed to initialize File Search store: %s", e)
            return

        while self._running:
            try:
                # 1. Process deletions first
                self._process_deletions()

                # 2. Check pending queue for eligible items
                self._process_pending_queue()

                # 3. Sleep for poll interval
                self.msleep(self.poll_interval_ms)

            except Exception as e:
                logger.error("Sync worker error: %s", e)
                self.msleep(5000)  # Brief pause on error

    def _process_pending_queue(self) -> None:
        """Process recordings that have passed their delay period."""
        now = time.time()
        ready = [(rid, t) for rid, t in self._pending_queue if t <= now]
        self._pending_queue = [(rid, t) for rid, t in self._pending_queue if t > now]

        total = len(ready)
        for i, (rec_id, _) in enumerate(ready):
            if not self._running:
                break
            self.sync_progress.emit(i + 1, total)
            self._sync_recording(rec_id)

    def _sync_recording(self, rec_id: str) -> None:
        """Sync a single recording to File Search."""
        try:
            # Get recording data
            recording = self.db.get_recording(rec_id)
            if not recording:
                logger.warning("Recording %s not found", rec_id)
                return

            # Skip short recordings
            duration = recording.get("duration_seconds", 0)
            if duration and duration < MIN_SYNC_DURATION_SECONDS:
                logger.debug("Skipping %s - too short (%.1fs)", rec_id, duration)
                return

            transcript = self.db.get_transcript(rec_id)
            notes = self.db.get_notes(rec_id)
            action_items = self.db.get_action_items(rec_id)

            # Skip if no meaningful content
            if not transcript and not notes:
                logger.debug("Skipping %s - no content to sync", rec_id)
                return

            # Format content
            content = format_meeting_document(recording, transcript, notes, action_items)
            content_hash = compute_content_hash(content)

            # Check if already synced with same content
            sync_status = self.db.get_sync_status(rec_id)
            if sync_status and sync_status.get("content_hash") == content_hash:
                logger.debug("Skipping %s - content unchanged", rec_id)
                return

            # Delete old document before re-uploading (prevents duplicates)
            if sync_status and sync_status.get("file_search_file_name"):
                old_doc_name = sync_status["file_search_file_name"]
                self.file_search.delete_meeting(old_doc_name)

            # Upload to File Search
            meeting_date = str(recording.get("started_at", ""))
            file_name = self.file_search.upload_meeting(rec_id, content, meeting_date)

            # Update sync status
            self.db.set_sync_status(
                rec_id, "synced", file_name=file_name, content_hash=content_hash
            )

            self.sync_completed.emit(rec_id)
            logger.info("Synced recording %s", rec_id)

        except FileSearchError as e:
            logger.error("Failed to sync %s: %s", rec_id, e)
            self.db.set_sync_status(rec_id, "error", error=str(e))
            self.sync_failed.emit(rec_id, str(e))
        except Exception as e:
            logger.error("Unexpected error syncing %s: %s", rec_id, e)
            self.db.set_sync_status(rec_id, "error", error=str(e))
            self.sync_failed.emit(rec_id, str(e))

    def _process_deletions(self) -> None:
        """Remove deleted recordings from File Search."""
        pending_deletions = self.db.get_pending_deletions()
        for record in pending_deletions:
            rec_id = record["recording_id"]
            file_name = record.get("file_search_file_name")
            if file_name:
                success = self.file_search.delete_meeting(file_name)
                if success:
                    # Remove from sync table
                    self.db.set_sync_status(rec_id, "removed")
                    logger.info("Removed %s from File Search", rec_id)

    def stop(self) -> None:
        """Stop the sync worker."""
        self._running = False
