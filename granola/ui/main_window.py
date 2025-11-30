"""Main application window - coordinates tabs and system integration."""

import logging

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget

from granola.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from granola.storage.database import Database
from granola.ui.history_tab import HistoryTab
from granola.ui.record_tab import RecordTab
from granola.ui.tray_icon import TrayIconManager

logger = logging.getLogger("granola")


class MainWindow(QMainWindow):
    """Main application window with Record and History tabs."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Granola Linux")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # Database
        self.db = Database()

        # Create tab modules
        self.history_tab = HistoryTab(self.db)
        self.record_tab = RecordTab(
            parent_window=self,
            db=self.db,
            on_recording_state_changed=self._on_recording_state_changed,
            on_history_changed=self._on_history_changed,
        )

        # Main layout with Tabs
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        # Tab 1: Record
        record_widget = QWidget()
        self.record_tab.setup(record_widget)
        tabs.addTab(record_widget, "Record")

        # Tab 2: History
        history_widget = QWidget()
        self.history_tab.setup(history_widget)
        tabs.addTab(history_widget, "History")

        # Setup shortcuts
        self._setup_shortcuts()

        # Setup tray icon
        self.tray_manager = TrayIconManager(self)
        self.tray_manager.setup()

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Start/Stop Recording (Ctrl+R)
        record_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        record_shortcut.activated.connect(self.toggle_recording)

        # Pause/Resume (Space)
        pause_shortcut = QShortcut(QKeySequence("Space"), self)
        pause_shortcut.activated.connect(self.toggle_pause)

        # Quit (Ctrl+Q)
        quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_shortcut.activated.connect(self.close)

    def toggle_recording(self):
        """Toggle recording state (for shortcuts and tray)."""
        self.record_tab.toggle_recording()

    def toggle_pause(self):
        """Toggle pause state (for shortcuts)."""
        self.record_tab.toggle_pause()

    def _on_recording_state_changed(self, is_recording: bool):
        """Handle recording state changes from record tab."""
        self.tray_manager.set_recording_state(is_recording)

    def _on_history_changed(self):
        """Handle history changes from record tab."""
        self.history_tab.refresh()

    def closeEvent(self, event):
        """Handle window close - minimize to tray or quit."""
        if self.tray_manager.is_visible():
            self.hide()
            event.ignore()
            self.tray_manager.show_message(
                "Granola",
                "Application minimized to tray. Right-click icon to quit.",
            )
        else:
            # Stop device monitor
            self.record_tab.stop_device_monitor()
            event.accept()
