"""System tray icon functionality."""

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QStyle, QSystemTrayIcon

logger = logging.getLogger("quinoa")


def _std_icon(window: QMainWindow, pixmap: QStyle.StandardPixmap) -> QIcon:
    """Return a standard icon, falling back to a null QIcon if style() is None."""
    style = window.style()
    if style is None:
        return QIcon()
    return style.standardIcon(pixmap)


class TrayIconManager(QObject):
    """Manages the system tray icon and its context menu."""

    # Emitted when the user clicks a notification balloon/toast.
    # Connected once here so it survives any future icon recreation.
    message_clicked = pyqtSignal()

    def __init__(self, parent_window: QMainWindow):
        super().__init__(parent_window)
        self._parent_window: QMainWindow = parent_window
        self.tray_icon: QSystemTrayIcon | None = None
        self.record_action: QAction | None = None

    def setup(self):
        """Initialize the system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this system")
            return False

        self.tray_icon = QSystemTrayIcon(self._parent_window)

        # Use a standard icon
        icon = _std_icon(self._parent_window, QStyle.StandardPixmap.SP_MediaPlay)
        if icon.isNull():
            logger.warning("Standard icon SP_MediaPlay not found")

        self.tray_icon.setIcon(icon)

        # Context Menu
        menu = QMenu()

        show_action = QAction("Show", self._parent_window)
        show_action.triggered.connect(self._parent_window.show)
        menu.addAction(show_action)

        self.record_action = QAction("Start Recording", self._parent_window)
        self.record_action.triggered.connect(self._parent_window.toggle_recording)
        menu.addAction(self.record_action)

        quit_action = QAction("Quit", self._parent_window)
        quit_action.triggered.connect(self._quit_application)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_activated)
        # Forward to our own signal so callers connect once and survive icon recreation
        self.tray_icon.messageClicked.connect(self.message_clicked)
        self.tray_icon.show()
        logger.debug("System tray icon initialized")
        return True

    def _on_activated(self, reason):
        """Handle tray icon activation (click)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._parent_window.isVisible():
                self._parent_window.hide()
            else:
                self._parent_window.show()
                self._parent_window.activateWindow()

    def _quit_application(self):
        """Quit the application (not minimize to tray)."""
        self._parent_window._quitting = True
        app = QApplication.instance()
        if app:
            app.quit()

    def set_recording_state(self, is_recording: bool):
        """Update tray icon to reflect recording state."""
        if not self.tray_icon or not self.record_action:
            return

        if is_recording:
            self.record_action.setText("Stop Recording")
            self.tray_icon.setIcon(
                _std_icon(self._parent_window, QStyle.StandardPixmap.SP_MediaStop)
            )
        else:
            self.record_action.setText("Start Recording")
            self.tray_icon.setIcon(
                _std_icon(self._parent_window, QStyle.StandardPixmap.SP_MediaPlay)
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
