"""System tray icon functionality."""

import logging

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

logger = logging.getLogger("quinoa")


class TrayIconManager:
    """Manages the system tray icon and its context menu."""

    def __init__(self, parent_window):
        self.parent = parent_window
        self.tray_icon = None
        self.record_action = None

    def setup(self):
        """Initialize the system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this system")
            return False

        self.tray_icon = QSystemTrayIcon(self.parent)

        # Use a standard icon
        icon = self.parent.style().standardIcon(self.parent.style().StandardPixmap.SP_MediaPlay)
        if icon.isNull():
            logger.warning("Standard icon SP_MediaPlay not found")

        self.tray_icon.setIcon(icon)

        # Context Menu
        menu = QMenu()

        show_action = QAction("Show", self.parent)
        show_action.triggered.connect(self.parent.show)
        menu.addAction(show_action)

        self.record_action = QAction("Start Recording", self.parent)
        self.record_action.triggered.connect(self.parent.toggle_recording)
        menu.addAction(self.record_action)

        quit_action = QAction("Quit", self.parent)
        quit_action.triggered.connect(self._quit_application)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.show()
        logger.debug("System tray icon initialized")
        return True

    def _on_activated(self, reason):
        """Handle tray icon activation (click)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.parent.isVisible():
                self.parent.hide()
            else:
                self.parent.show()
                self.parent.activateWindow()

    def _quit_application(self):
        """Quit the application (not minimize to tray)."""
        self.parent._quitting = True
        QApplication.instance().quit()

    def set_recording_state(self, is_recording: bool):
        """Update tray icon to reflect recording state."""
        if not self.tray_icon:
            return

        if is_recording:
            self.record_action.setText("Stop Recording")
            self.tray_icon.setIcon(
                self.parent.style().standardIcon(self.parent.style().StandardPixmap.SP_MediaStop)
            )
        else:
            self.record_action.setText("Start Recording")
            self.tray_icon.setIcon(
                self.parent.style().standardIcon(self.parent.style().StandardPixmap.SP_MediaPlay)
            )

    def is_visible(self) -> bool:
        """Check if tray icon is visible."""
        return self.tray_icon is not None and self.tray_icon.isVisible()

    def show_message(self, title: str, message: str, duration_ms: int = 2000):
        """Show a tray notification message."""
        if self.tray_icon:
            self.tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                duration_ms,
            )
