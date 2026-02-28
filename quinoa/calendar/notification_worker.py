"""Background worker for meeting notifications and recording reminders."""

import logging
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QMutex, QThread, QWaitCondition, pyqtSignal

from quinoa.config import config
from quinoa.storage.database import Database

logger = logging.getLogger("quinoa")

# Check for notifications every 30 seconds
NOTIFICATION_POLL_INTERVAL_MS = 30 * 1000

# Notify this many minutes before a meeting starts
PRE_MEETING_NOTIFY_MINUTES = 5


class NotificationWorker(QThread):
    """Background thread for meeting notifications and recording reminders.

    Polls the database for today's calendar events and fires notifications:
    1. Pre-meeting notification: N minutes before a meeting starts
    2. Recording reminder: when a meeting has started but no recording is active

    Uses QSystemTrayIcon notifications via signals to the main window.
    """

    # Signals
    notify = pyqtSignal(str, str, int)  # title, message, duration_ms
    recording_reminder = pyqtSignal(str, str)  # event_id, meeting_title

    def __init__(self, db: Database, parent: QThread | None = None):
        super().__init__(parent)
        self.db = db
        self._running = False
        self._is_recording = False
        self._mutex = QMutex()
        self._wake_condition = QWaitCondition()

        # Track which events we've already notified about (reset daily)
        self._notified_upcoming: set[str] = set()
        self._notified_reminder: set[str] = set()
        self._last_reset_date: date | None = None

    def run(self) -> None:
        """Main worker loop."""
        self._running = True
        logger.info("Notification worker started")

        while self._running:
            self._check_notifications()

            # Sleep until next poll or wake-up
            self._mutex.lock()
            if self._running:
                self._wake_condition.wait(self._mutex, NOTIFICATION_POLL_INTERVAL_MS)
            self._mutex.unlock()

        logger.info("Notification worker stopped")

    def stop(self) -> None:
        """Stop the worker gracefully."""
        self._mutex.lock()
        self._running = False
        self._wake_condition.wakeAll()
        self._mutex.unlock()

    def set_recording_state(self, is_recording: bool) -> None:
        """Update the recording state (called from main thread)."""
        self._is_recording = is_recording

    def _reset_daily_state(self) -> None:
        """Reset notification tracking at the start of each day."""
        today = datetime.now().date()
        if self._last_reset_date != today:
            self._notified_upcoming.clear()
            self._notified_reminder.clear()
            self._last_reset_date = today

    def _check_notifications(self) -> None:
        """Check for meetings that need notifications."""
        if not config.get("notifications_enabled", True):
            return

        self._reset_daily_state()

        try:
            events = self.db.get_todays_calendar_events()
        except Exception as e:
            logger.warning("Notification worker: failed to get events: %s", e)
            return

        now = datetime.now()
        video_only = config.get("notify_video_only", True)
        grace_minutes = config.get("reminder_grace_period_minutes", 2)

        for event in events:
            event_id = event.get("event_id", "")
            title = event.get("title", "Meeting")
            meet_link = event.get("meet_link")
            start_time_raw = event.get("start_time")
            recording_id = event.get("recording_id") or event.get("rec_id")

            # Skip if video_only is enabled and no video link
            if video_only and not meet_link:
                continue

            # Parse start time
            start_time = self._parse_time(start_time_raw)
            if not start_time:
                continue

            # 1. Pre-meeting notification
            self._check_upcoming_notification(event_id, title, start_time, now)

            # 2. Recording reminder
            if config.get("recording_reminder_enabled", True):
                self._check_recording_reminder(
                    event_id, title, start_time, now, recording_id, grace_minutes
                )

    def _check_upcoming_notification(
        self,
        event_id: str,
        title: str,
        start_time: datetime,
        now: datetime,
    ) -> None:
        """Send a notification when a meeting is about to start."""
        if event_id in self._notified_upcoming:
            return

        minutes_until = (start_time - now).total_seconds() / 60

        # Notify if meeting starts within the notification window
        # but hasn't started yet
        if 0 < minutes_until <= PRE_MEETING_NOTIFY_MINUTES:
            mins = int(minutes_until)
            time_str = start_time.strftime("%-I:%M %p")
            if mins <= 1:
                message = f"Starting now at {time_str}"
            else:
                message = f"Starts in {mins} minutes at {time_str}"

            self.notify.emit(f"Upcoming: {title}", message, 5000)
            self._notified_upcoming.add(event_id)
            logger.info("Notification sent for upcoming meeting: %s", title)

    def _check_recording_reminder(
        self,
        event_id: str,
        title: str,
        start_time: datetime,
        now: datetime,
        recording_id: str | None,
        grace_minutes: int,
    ) -> None:
        """Send a reminder if a meeting started but no recording is active."""
        if event_id in self._notified_reminder:
            return

        # Already has a recording linked — no reminder needed
        if recording_id:
            return

        # Currently recording — no reminder needed
        if self._is_recording:
            return

        # Check if meeting started + grace period has elapsed
        reminder_threshold = start_time + timedelta(minutes=grace_minutes)
        if now < reminder_threshold:
            return

        # Don't remind for meetings that ended (or ended a while ago)
        # Give a 30-minute window after start for the reminder to be useful
        if now > start_time + timedelta(minutes=30):
            return

        self.recording_reminder.emit(event_id, title)
        self._notified_reminder.add(event_id)
        logger.info("Recording reminder sent for meeting: %s", title)

    @staticmethod
    def _parse_time(raw_time: str | datetime | None) -> datetime | None:
        """Parse a time value from the database."""
        if raw_time is None:
            return None
        if isinstance(raw_time, datetime):
            return raw_time
        try:
            # SQLite stores as ISO format string
            return datetime.fromisoformat(raw_time)
        except (ValueError, TypeError):
            return None
