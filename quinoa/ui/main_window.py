"""Main application window - 3-column layout."""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QSplitter

from quinoa.audio.compression_worker import CompressionWorker
from quinoa.calendar import is_authenticated as calendar_is_authenticated
from quinoa.calendar.notification_worker import NotificationWorker
from quinoa.calendar.sync_worker import CalendarSyncWorker
from quinoa.config import config
from quinoa.constants import (
    FILE_SEARCH_DELAY_MS,
    LEFT_PANEL_MIN_WIDTH,
    LEFT_PANEL_WIDTH,
    RIGHT_PANEL_WIDTH,
    SPLITTER_DEFAULT_SIZES,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from quinoa.search.file_search import FileSearchManager
from quinoa.search.sync_worker import SyncWorker
from quinoa.storage.database import Database
from quinoa.ui.calendar_panel import CalendarPanel
from quinoa.ui.middle_panel import MiddlePanel
from quinoa.ui.right_panel import RightPanel
from quinoa.ui.settings_dialog import SettingsDialog
from quinoa.ui.tray_icon import TrayIconManager

logger = logging.getLogger("quinoa")


class MainWindow(QMainWindow):
    """Main application window with 3-column layout."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Quinoa")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # Database
        self.db = Database()

        # File Search components (initialized later if enabled)
        self._file_search: FileSearchManager | None = None
        self._sync_worker: SyncWorker | None = None

        # Calendar sync worker (initialized later if authenticated)
        self._calendar_sync_worker: CalendarSyncWorker | None = None

        # Notification worker (initialized later if calendar is authenticated)
        self._notification_worker: NotificationWorker | None = None

        # Compression worker (for converting WAV -> FLAC after transcription)
        self._compression_worker: CompressionWorker | None = None

        # Flag to distinguish quit vs minimize-to-tray
        self._quitting = False

        # Create main splitter (horizontal, 3 columns)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(6)
        self.setCentralWidget(self.splitter)

        # Left panel - Calendar/Navigation
        self.left_panel = CalendarPanel(self.db)
        self.left_panel.setMinimumWidth(LEFT_PANEL_MIN_WIDTH)
        self.left_panel.meeting_selected.connect(self._on_calendar_meeting_selected)
        self.left_panel.recording_selected.connect(self._on_meeting_selected)
        self.left_panel.new_meeting_requested.connect(self._on_new_meeting)
        self.left_panel.settings_requested.connect(self._open_settings)
        self.splitter.addWidget(self.left_panel)

        # Middle panel - Notes/Transcript + Recording controls
        self.middle_panel = MiddlePanel(
            db=self.db,
            on_history_changed=self._on_history_changed,
        )
        self.middle_panel.recording_state_changed.connect(self._on_recording_state_changed)
        self.middle_panel.recording_started.connect(self._on_recording_started)
        self.middle_panel.recording_stopped.connect(self._on_recording_stopped)
        self.middle_panel.silence_detected.connect(self._on_silence_detected)
        self.left_panel.meeting_renamed.connect(self.middle_panel.on_meeting_renamed)
        self.splitter.addWidget(self.middle_panel)

        # Right panel - AI Chat
        self.right_panel = RightPanel(db=self.db)
        self.splitter.addWidget(self.right_panel)

        # Restore splitter sizes from config or use defaults
        saved_sizes = config.get("splitter_sizes")
        if saved_sizes and len(saved_sizes) == 3:
            self.splitter.setSizes(saved_sizes)
        else:
            self.splitter.setSizes(SPLITTER_DEFAULT_SIZES)

        # Restore collapsed states from config
        self._left_collapsed = config.get("left_panel_collapsed", False)
        self._right_collapsed = config.get("right_panel_collapsed", False)
        self._left_size = LEFT_PANEL_WIDTH
        self._right_size = RIGHT_PANEL_WIDTH

        # Apply collapsed states if needed
        if self._left_collapsed:
            sizes = self.splitter.sizes()
            self._left_size = sizes[0] if sizes[0] > 0 else LEFT_PANEL_WIDTH
            sizes[0] = 0
            self.splitter.setSizes(sizes)

        if self._right_collapsed:
            sizes = self.splitter.sizes()
            self._right_size = sizes[2] if sizes[2] > 0 else RIGHT_PANEL_WIDTH
            sizes[2] = 0
            self.splitter.setSizes(sizes)

        # Setup shortcuts
        self._setup_shortcuts()

        # Setup tray icon
        self.tray_manager = TrayIconManager(self)
        self.tray_manager.setup()

        # Initialize File Search if enabled
        self._init_file_search()

        # Initialize Calendar sync if authenticated
        self._init_calendar_sync()

        # Initialize notification worker if calendar is authenticated
        self._init_notification_worker()

        # Initialize compression worker for background WAV -> FLAC conversion
        self._init_compression_worker()

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Start/Stop Recording (Ctrl+R)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.toggle_recording)

        # Pause/Resume (Space) - only when not editing text
        QShortcut(QKeySequence("Space"), self).activated.connect(self._handle_space)

        # Focus notes (Ctrl+N)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._focus_notes)

        # Toggle left panel (Ctrl+[)
        QShortcut(QKeySequence("Ctrl+["), self).activated.connect(self._toggle_left_panel)

        # Toggle right panel (Ctrl+])
        QShortcut(QKeySequence("Ctrl+]"), self).activated.connect(self._toggle_right_panel)

        # Quit (Ctrl+Q)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.close)

    def _handle_space(self):
        """Handle space key - pause/resume if recording, otherwise ignore."""
        # Only pause/resume if we're recording and not focused on a text input
        focus_widget = self.focusWidget()
        if focus_widget and hasattr(focus_widget, "toPlainText"):
            # Focus is on a text editor, let it handle space
            return

        if self.middle_panel.is_recording:
            self.middle_panel.toggle_pause()

    def toggle_recording(self):
        """Toggle recording state."""
        self.middle_panel.toggle_recording()

    def _focus_notes(self):
        """Focus the notes editor."""
        self.middle_panel.focus_notes()

    def _toggle_left_panel(self):
        """Toggle left panel visibility."""
        sizes = self.splitter.sizes()

        if self._left_collapsed:
            # Expand
            sizes[0] = self._left_size
            self._left_collapsed = False
        else:
            # Collapse
            self._left_size = sizes[0] if sizes[0] > 0 else LEFT_PANEL_WIDTH
            sizes[0] = 0
            self._left_collapsed = True

        self.splitter.setSizes(sizes)

    def _toggle_right_panel(self):
        """Toggle right panel visibility."""
        sizes = self.splitter.sizes()

        if self._right_collapsed:
            # Expand
            sizes[2] = self._right_size
            self._right_collapsed = False
        else:
            # Collapse
            self._right_size = sizes[2] if sizes[2] > 0 else RIGHT_PANEL_WIDTH
            sizes[2] = 0
            self._right_collapsed = True

        self.splitter.setSizes(sizes)

    def _init_file_search(self) -> None:
        """Initialize File Search if enabled and API key is configured."""
        api_key = config.get("api_key")
        file_search_enabled = config.get("file_search_enabled", False)

        if not api_key or not file_search_enabled:
            logger.debug(
                "File Search not initialized: enabled=%s, has_key=%s",
                file_search_enabled,
                bool(api_key),
            )
            return

        try:
            # Get existing store name if any
            store_name = config.get("file_search_store_name")

            # Initialize File Search manager
            self._file_search = FileSearchManager(api_key, store_name)
            self.right_panel.set_file_search(self._file_search)

            # Initialize sync worker
            self._sync_worker = SyncWorker(self.db, self._file_search)
            self._sync_worker.store_ready.connect(self._on_store_ready)
            self._sync_worker.sync_completed.connect(self._on_sync_completed)
            self._sync_worker.sync_failed.connect(self._on_sync_failed)

            # Connect transcription completion to sync queue
            delay_seconds = FILE_SEARCH_DELAY_MS // 1000
            self.middle_panel.transcription_completed.connect(
                lambda rec_id: self._sync_worker.queue_for_sync(rec_id, delay_seconds)
                if self._sync_worker
                else None
            )

            # Start sync worker and queue existing unsynced recordings
            self._sync_worker.queue_all_unsynced()
            self._sync_worker.start()

            logger.info("File Search initialized")

        except Exception as e:
            logger.error("Failed to initialize File Search: %s", e)
            self._file_search = None
            self._sync_worker = None

    def _init_calendar_sync(self) -> None:
        """Initialize Calendar sync worker if authenticated."""
        if self._calendar_sync_worker is not None:
            logger.debug("Calendar sync worker already running")
            return

        if not calendar_is_authenticated():
            logger.debug("Calendar sync not initialized: not authenticated")
            return

        try:
            self._calendar_sync_worker = CalendarSyncWorker(self.db)
            self._calendar_sync_worker.sync_started.connect(self._on_calendar_sync_started)
            self._calendar_sync_worker.sync_completed.connect(self._on_calendar_sync_completed)
            self._calendar_sync_worker.sync_failed.connect(self._on_calendar_sync_failed)
            self._calendar_sync_worker.events_updated.connect(self._on_calendar_events_updated)
            self._calendar_sync_worker.start()
            logger.info("Calendar sync worker started")
        except Exception as e:
            logger.error("Failed to initialize Calendar sync: %s", e)
            self._calendar_sync_worker = None

    def _stop_calendar_sync(self) -> None:
        """Stop the calendar sync worker."""
        if self._calendar_sync_worker:
            self._calendar_sync_worker.stop()
            self._calendar_sync_worker.wait(2000)
            self._calendar_sync_worker = None
            logger.info("Calendar sync worker stopped")

    def _init_notification_worker(self) -> None:
        """Initialize the notification worker if calendar is authenticated."""
        if self._notification_worker is not None:
            logger.debug("Notification worker already running")
            return

        if not calendar_is_authenticated():
            logger.debug("Notification worker not initialized: calendar not authenticated")
            return

        try:
            self._notification_worker = NotificationWorker(self.db)
            self._notification_worker.notify.connect(self._on_meeting_notification)
            self._notification_worker.recording_reminder.connect(self._on_recording_reminder)

            # Feed recording state to the notification worker
            self.middle_panel.recording_state_changed.connect(
                self._notification_worker.set_recording_state
            )

            # Connect tray notification click to show window (via TrayIconManager signal
            # so the connection survives any future icon recreation)
            self.tray_manager.message_clicked.connect(self._on_notification_clicked)

            self._notification_worker.start()
            logger.info("Notification worker started")
        except Exception as e:
            logger.error("Failed to initialize notification worker: %s", e)
            self._notification_worker = None

    def _stop_notification_worker(self) -> None:
        """Stop the notification worker."""
        if self._notification_worker:
            self._notification_worker.stop()
            self._notification_worker.wait(2000)
            self._notification_worker = None
            logger.info("Notification worker stopped")

    def _on_meeting_notification(self, title: str, message: str, duration_ms: int) -> None:
        """Handle meeting notification from worker."""
        self.tray_manager.show_message(title, message, duration_ms)

    def _on_recording_reminder(self, event_id: str, title: str) -> None:
        """Handle recording reminder — meeting started but not recording."""
        self.tray_manager.show_message(
            "Not Recording",
            f'Your meeting "{title}" has started.\nClick to open Quinoa.',
            10000,  # Persistent-ish: 10 seconds
        )

    def _on_notification_clicked(self) -> None:
        """Handle user clicking a notification — show and activate the window."""
        self.show()
        self.activateWindow()

    def _on_silence_detected(self) -> None:
        """Handle extended silence during recording."""
        self.tray_manager.show_message(
            "Silence Detected",
            "No audio activity for 90 seconds.\nYou may want to stop recording.",
            10000,
        )

    def _init_compression_worker(self) -> None:
        """Initialize background compression worker."""
        try:
            self._compression_worker = CompressionWorker(self.db)
            self._compression_worker.compression_started.connect(
                lambda rec_id: logger.debug("Compressing recording %s", rec_id)
            )
            self._compression_worker.compression_completed.connect(
                lambda rec_id, count: logger.info(
                    "Compressed %d files for recording %s", count, rec_id
                )
            )
            self._compression_worker.compression_failed.connect(
                lambda rec_id, err: logger.warning("Compression failed for %s: %s", rec_id, err)
            )
            self._compression_worker.start()
            logger.info("Compression worker started")
        except Exception as e:
            logger.error("Failed to start compression worker: %s", e)
            self._compression_worker = None

    def _stop_compression_worker(self) -> None:
        """Stop the compression worker."""
        if self._compression_worker:
            self._compression_worker.stop()
            self._compression_worker.wait(2000)
            self._compression_worker = None
            logger.info("Compression worker stopped")

    def _on_calendar_sync_started(self) -> None:
        """Handle calendar sync started."""
        logger.debug("Calendar sync started")

    def _on_calendar_sync_completed(self, count: int) -> None:
        """Handle calendar sync completed."""
        logger.debug("Calendar sync completed: %d events", count)

    def _on_calendar_sync_failed(self, error: str) -> None:
        """Handle calendar sync failed."""
        logger.warning("Calendar sync failed: %s", error)

    def _on_calendar_events_updated(self, changed: bool) -> None:
        """Handle calendar events updated - refresh left panel only if data changed."""
        if changed:
            self.left_panel.refresh()

    def _on_calendar_connected(self) -> None:
        """Handle calendar connection from settings dialog."""
        # Start the sync worker
        self._init_calendar_sync()
        # Start notification worker
        self._init_notification_worker()
        # Trigger immediate sync
        if self._calendar_sync_worker:
            self._calendar_sync_worker.sync_now()

    def _on_calendar_disconnected(self) -> None:
        """Handle calendar disconnection from settings dialog."""
        self._stop_calendar_sync()
        self._stop_notification_worker()
        # Clear calendar events from database
        self.db.clear_calendar_events()
        # Refresh left panel
        self.left_panel.refresh()

    def _on_store_ready(self, store_name: str) -> None:
        """Handle store ready signal - save store name to config."""
        config.set("file_search_store_name", store_name)
        self.right_panel.set_enabled(True)
        logger.info("File Search store ready: %s", store_name)

    def _on_sync_completed(self, rec_id: str) -> None:
        """Handle successful sync."""
        logger.debug("Synced recording %s to File Search", rec_id)

    def _on_sync_failed(self, rec_id: str, error: str) -> None:
        """Handle sync failure."""
        logger.warning("Failed to sync recording %s: %s", rec_id, error)

    def _on_meeting_selected(self, rec_id: str):
        """Handle recording selection from left panel."""
        self.middle_panel.load_meeting(rec_id)

    def _on_calendar_meeting_selected(self, event_id: str):
        """Handle calendar event selection (unrecorded meeting)."""
        # Load the calendar event details in the middle panel
        self.middle_panel.load_calendar_event(event_id)

    def _on_new_meeting(self):
        """Handle new meeting request - return to idle/recording mode."""
        self.middle_panel.clear_view()

    def _open_settings(self):
        """Open settings dialog."""
        dialog = SettingsDialog(self)
        dialog.calendar_connected.connect(self._on_calendar_connected)
        dialog.calendar_disconnected.connect(self._on_calendar_disconnected)
        dialog.exec()

    def _on_history_changed(self):
        """Handle history changes."""
        self.left_panel.refresh()

    def _on_recording_state_changed(self, is_recording: bool):
        """Handle recording state changes."""
        self.tray_manager.set_recording_state(is_recording)

    def _on_recording_started(self, rec_id: str):
        """Handle recording started."""
        # Select the new recording in the left panel
        self.left_panel.refresh()
        self.left_panel.select_meeting(rec_id)

    def _on_recording_stopped(self, rec_id: str):
        """Handle recording stopped."""
        self.left_panel.refresh()

    def _save_window_state(self):
        """Save window state (splitter sizes, collapsed states) to config."""
        # Save current splitter sizes (only if not collapsed)
        sizes = self.splitter.sizes()

        # If panels are collapsed, restore their saved sizes for persistence
        if self._left_collapsed:
            sizes[0] = self._left_size
        if self._right_collapsed:
            sizes[2] = self._right_size

        config.set("splitter_sizes", sizes)
        config.set("left_panel_collapsed", self._left_collapsed)
        config.set("right_panel_collapsed", self._right_collapsed)

    def closeEvent(self, a0):
        """Handle window close - minimize to tray or quit."""
        if self.tray_manager.is_visible() and not self._quitting:
            # Minimize to tray instead of closing
            self.hide()
            a0.ignore()
            self.tray_manager.show_message(
                "Quinoa",
                "Minimized to tray. Right-click icon to quit.",
            )
        else:
            # Actually quit - save state and clean up
            self._save_window_state()
            # Stop sync worker
            if self._sync_worker:
                self._sync_worker.stop()
                self._sync_worker.wait(2000)  # Wait up to 2 seconds
            # Stop calendar sync worker
            self._stop_calendar_sync()
            # Stop notification worker
            self._stop_notification_worker()
            # Stop compression worker
            self._stop_compression_worker()
            # Stop device monitor
            self.middle_panel.stop_device_monitor()
            a0.accept()
