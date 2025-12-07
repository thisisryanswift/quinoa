"""Main application window - 3-column layout."""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QSplitter

from quinoa.config import config
from quinoa.constants import (
    FILE_SEARCH_DELAY_MS,
    LEFT_PANEL_WIDTH,
    RIGHT_PANEL_WIDTH,
    SPLITTER_DEFAULT_SIZES,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from quinoa.search.file_search import FileSearchManager
from quinoa.search.sync_worker import SyncWorker
from quinoa.storage.database import Database
from quinoa.ui.left_panel import LeftPanel
from quinoa.ui.middle_panel import MiddlePanel
from quinoa.ui.right_panel import RightPanel
from quinoa.ui.settings_dialog import SettingsDialog
from quinoa.ui.styles import SPLITTER_STYLE
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

        # Flag to distinguish quit vs minimize-to-tray
        self._quitting = False

        # Create main splitter (horizontal, 3 columns)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)  # Wider handle for easier grabbing
        self.splitter.setStyleSheet(SPLITTER_STYLE)
        self.setCentralWidget(self.splitter)

        # Left panel - Navigation
        self.left_panel = LeftPanel(self.db)
        self.left_panel.meeting_selected.connect(self._on_meeting_selected)
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
        """Handle meeting selection from left panel."""
        self.middle_panel.load_meeting(rec_id)

    def _on_new_meeting(self):
        """Handle new meeting request - return to idle/recording mode."""
        self.middle_panel.clear_view()

    def _open_settings(self):
        """Open settings dialog."""
        dialog = SettingsDialog(self)
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

    def closeEvent(self, event):
        """Handle window close - minimize to tray or quit."""
        if self.tray_manager.is_visible() and not self._quitting:
            # Minimize to tray instead of closing
            self.hide()
            event.ignore()
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
            # Stop device monitor
            self.middle_panel.stop_device_monitor()
            event.accept()
