"""Background worker for syncing Google Calendar events."""

import logging

from PyQt6.QtCore import QMutex, QThread, QWaitCondition, pyqtSignal

from quinoa.calendar.auth import get_credentials, is_authenticated
from quinoa.calendar.client import CalendarClient
from quinoa.config import config
from quinoa.storage.database import Database

logger = logging.getLogger("quinoa")

# Default sync interval (5 minutes)
DEFAULT_SYNC_INTERVAL_MS = 5 * 60 * 1000


class CalendarSyncWorker(QThread):
    """Background thread for syncing calendar events."""

    # Signals
    sync_started = pyqtSignal()
    sync_completed = pyqtSignal(int)  # number of events synced
    sync_failed = pyqtSignal(str)  # error message
    events_updated = pyqtSignal(bool)  # emitted with True if events changed, False otherwise

    def __init__(
        self,
        db: Database,
        sync_interval_ms: int = DEFAULT_SYNC_INTERVAL_MS,
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.sync_interval_ms = sync_interval_ms
        self._running = False
        self._mutex = QMutex()
        self._wake_condition = QWaitCondition()
        self._sync_requested = False

    def run(self) -> None:
        """Main worker loop."""
        self._running = True

        while self._running:
            if is_authenticated():
                self._sync_today()

            # Wait for either timeout or explicit wake-up
            self._mutex.lock()
            if not self._sync_requested and self._running:
                self._wake_condition.wait(self._mutex, self.sync_interval_ms)
            self._sync_requested = False
            self._mutex.unlock()

        logger.info("Calendar sync worker stopped")

    def stop(self) -> None:
        """Stop the worker gracefully."""
        self._mutex.lock()
        self._running = False
        self._wake_condition.wakeAll()
        self._mutex.unlock()

    def sync_now(self) -> None:
        """Request immediate sync by waking the worker thread."""
        self._mutex.lock()
        self._sync_requested = True
        self._wake_condition.wakeAll()
        self._mutex.unlock()

    def _sync_today(self) -> None:
        """Fetch today's events and update database."""
        try:
            self.sync_started.emit()

            creds = get_credentials()
            if not creds:
                self.sync_failed.emit("Not authenticated")
                return

            client = CalendarClient(creds)

            # Get configured calendar IDs (default to primary)
            calendar_ids = config.get("calendar_ids", ["primary"])

            # Fetch today's video meetings
            video_only = config.get("calendar_video_only", True)
            events = client.get_todays_events(calendar_ids, video_only=video_only)

            # Update database and check if anything changed
            changes = 0
            if events:
                changes = self.db.upsert_calendar_events(events)

            logger.info(
                "Calendar sync complete: %d events, %d changes (video_only=%s)",
                len(events),
                changes,
                video_only,
            )
            self.sync_completed.emit(len(events))
            self.events_updated.emit(changes > 0)

        except Exception as e:
            logger.error("Calendar sync failed: %s", e)
            self.sync_failed.emit(str(e))
