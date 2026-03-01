"""System tray icon functionality."""

import contextlib
import logging
import threading

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QStyle, QSystemTrayIcon

try:
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

logger = logging.getLogger("quinoa")


class DBusListener(QThread):
    """Background thread to listen for D-Bus notification action signals."""
    action_invoked = pyqtSignal(int, str)  # (notification_id, action_key)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = threading.Event()
        self._running.set()

    def run(self):
        try:
            with open_dbus_connection(bus='SESSION') as connection:
                # Add match rule to receive ActionInvoked signals
                match_rule = "type='signal',interface='org.freedesktop.Notifications',member='ActionInvoked'"
                bus_addr = DBusAddress('/org/freedesktop/DBus', bus_name='org.freedesktop.DBus', interface='org.freedesktop.DBus')
                msg = new_method_call(bus_addr, 'AddMatch', 's', (match_rule,))
                connection.send_and_get_reply(msg)

                while self._running.is_set():
                    try:
                        msg = connection.receive(timeout=1.0)
                        if (
                            msg
                            and msg.header.message_type.name == 'SIGNAL'
                            and msg.header.fields.get(3) == 'ActionInvoked'
                        ):
                            # Body contains (id: uint32, action_key: string)
                            notif_id = msg.body[0]
                            action_key = msg.body[1]
                            self.action_invoked.emit(notif_id, action_key)
                    except TimeoutError:
                        continue
        except Exception as e:
            logger.debug("DBusListener error (expected during shutdown): %s", e)

    def stop(self):
        self._running.clear()
        self.wait()


class DBusNotifier(QObject):
    """Manages Freedesktop D-Bus notifications with action buttons."""
    start_recording_requested = pyqtSignal(str)  # event_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._address = DBusAddress(
            '/org/freedesktop/Notifications',
            bus_name='org.freedesktop.Notifications',
            interface='org.freedesktop.Notifications'
        )
        self._listener = None
        self._event_ids: dict[int, str] = {}  # Map notification ID to event_id
        self._connection = None

    def setup(self) -> bool:
        if not HAS_DBUS:
            return False
        try:
            # Persistent connection for sending notifications
            self._connection = open_dbus_connection(bus='SESSION')

            self._listener = DBusListener()
            self._listener.action_invoked.connect(self._on_action_invoked)
            self._listener.start()
            return True
        except Exception as e:
            logger.warning("Failed to setup DBusNotifier: %s", e)
            return False

    def _on_action_invoked(self, notif_id: int, action_key: str):
        """Handle signal from listener, verifying it belongs to Quinoa."""
        if action_key == "start_rec" and notif_id in self._event_ids:
            event_id = self._event_ids.pop(notif_id)
            self.start_recording_requested.emit(event_id)

    def show_message(
        self,
        title: str,
        message: str,
        duration_ms: int = 2000,
        event_id: str | None = None,
        show_action: bool = False
    ):
        if not self._connection:
            return

        try:
            actions = []
            if show_action:
                actions = ["start_rec", "Start Recording"]

            # hints dictionary. 'urgency' 1 is normal
            hints = {"urgency": ("y", 1)}

            msg = new_method_call(self._address, 'Notify', 'susssasa{sv}i', (
                'Quinoa',     # app_name
                0,            # replaces_id
                'media-record', # app_icon
                title,        # summary
                message,      # body
                actions,      # actions
                hints,        # hints
                duration_ms   # expire_timeout
            ))

            # send_and_get_reply() returns a Message object
            reply = self._connection.send_and_get_reply(msg)

            if event_id and reply and reply.body:
                notif_id = reply.body[0]
                self._event_ids[notif_id] = event_id

        except Exception as e:
            logger.warning("Failed to send DBus notification: %s", e)

    def cleanup(self):
        if self._listener:
            self._listener.stop()
        if self._connection:
            with contextlib.suppress(Exception):
                self._connection.close()
            self._connection = None


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
    start_recording_requested = pyqtSignal(str) # event_id

    def __init__(self, parent_window: QMainWindow):
        super().__init__(parent_window)
        self._parent_window: QMainWindow = parent_window
        self.tray_icon: QSystemTrayIcon | None = None
        self.record_action: QAction | None = None
        self._dbus_notifier = None

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

        # Setup DBus Notifier if available
        self._dbus_notifier = DBusNotifier(self)
        if not self._dbus_notifier.setup():
            self._dbus_notifier = None
        else:
            self._dbus_notifier.start_recording_requested.connect(self.start_recording_requested)

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

    def cleanup(self):
        """Clean up resources before exit."""
        if self._dbus_notifier:
            self._dbus_notifier.cleanup()

    def show_message(self, title: str, message: str, duration_ms: int = 2000, event_id: str | None = None, show_action: bool = False):
        """Show a tray notification message."""
        if self._dbus_notifier:
            self._dbus_notifier.show_message(title, message, duration_ms, event_id, show_action)
        elif self.tray_icon:
            self.tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                duration_ms,
            )
