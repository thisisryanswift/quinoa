import argparse
import os
import signal
import sys
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QSocketNotifier, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from quinoa.constants import APP_ICON_PATH
from quinoa.logging import logger, setup_logging
from quinoa.ui.main_window import MainWindow


def load_app_icon() -> QIcon:
    """Load the application icon and ensure it's square to prevent smushing."""
    pixmap = QPixmap(APP_ICON_PATH)
    if pixmap.isNull():
        return QIcon()

    w, h = pixmap.width(), pixmap.height()
    if w == h:
        return QIcon(pixmap)

    # Create a square transparent canvas
    size = max(w, h)
    squared = QPixmap(size, size)
    squared.fill(Qt.GlobalColor.transparent)

    # Center the original icon on the square canvas
    painter = QPainter(squared)
    x = (size - w) // 2
    y = (size - h) // 2
    painter.drawPixmap(x, y, pixmap)
    painter.end()

    return QIcon(squared)


def _noop_signal_handler(signum: int, frame: Any | None) -> None:
    """No-op SIGINT handler: CPython's wakeup fd does the real work."""
    pass


class SigintBridge(QObject):
    """Bridge terminal SIGINT into the Qt event loop using CPython's wakeup fd.

    CPython writes the signal byte to a registered nonblocking pipe descriptor
    from its low-level signal machinery; a QSocketNotifier observes the read
    descriptor and emits one quit request on the Qt main thread. Repeated
    SIGINTs are coalesced and never force-terminate.
    """

    quit_requested = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._read_fd: int = -1
        self._write_fd: int = -1
        self._notifier: QSocketNotifier | None = None
        self._previous_wakeup_fd: int = -1
        self._previous_handler: Callable[[int, Any], Any] | int | None = None
        self._wakeup_registered = False
        self._handler_installed = False
        self._disposed = False
        self._emitted = False
        self._setup()

    def _setup(self) -> None:
        try:
            self._read_fd, self._write_fd = os.pipe()
            os.set_blocking(self._read_fd, False)
            os.set_blocking(self._write_fd, False)

            self._previous_wakeup_fd = signal.set_wakeup_fd(
                self._write_fd, warn_on_full_buffer=False
            )
            self._wakeup_registered = True

            self._previous_handler = signal.signal(signal.SIGINT, _noop_signal_handler)
            self._handler_installed = True

            self._notifier = QSocketNotifier(
                self._read_fd,
                QSocketNotifier.Type.Read,
                self,  # type: ignore[call-overload]
            )
            self._notifier.activated.connect(self._on_activated)
        except Exception:
            self._rollback_setup()
            raise

    def _rollback_setup(self) -> None:
        """Best-effort reverse-order rollback of partial setup.

        Preserves the original setup exception (this method is called from the
        ``except`` block that raised it). Fallback signal behaviour is not
        installed.
        """
        if self._handler_installed:
            try:
                signal.signal(
                    signal.SIGINT,
                    self._previous_handler
                    if self._previous_handler is not None
                    else signal.SIG_DFL,
                )
            except Exception:
                logger.exception("Failed to restore previous SIGINT handler during rollback")
            self._handler_installed = False

        if self._wakeup_registered:
            try:
                signal.set_wakeup_fd(self._previous_wakeup_fd)
            except Exception:
                logger.exception("Failed to restore previous wakeup fd during rollback")
            self._wakeup_registered = False

        if self._notifier is not None:
            try:
                self._notifier.setEnabled(False)
                self._notifier.deleteLater()
            except Exception:
                logger.exception("Failed to disable notifier during rollback")
            self._notifier = None

        if self._read_fd != -1:
            try:
                os.close(self._read_fd)
            except Exception:
                logger.exception("Failed to close read pipe during rollback")
            self._read_fd = -1

        if self._write_fd != -1:
            try:
                os.close(self._write_fd)
            except Exception:
                logger.exception("Failed to close write pipe during rollback")
            self._write_fd = -1

    def _on_activated(self, _socket: int = -1) -> None:
        """Drain pending bytes, unregister wakeup fd, and emit once."""
        if self._emitted:
            return
        self._emitted = True

        # Drain any pending signal bytes.
        while True:
            try:
                data = os.read(self._read_fd, 256)
            except OSError:
                break
            if not data:
                break

        # Prevent further SIGINT writes from filling the pipe during shutdown.
        if self._wakeup_registered:
            try:
                signal.set_wakeup_fd(-1)
            except Exception:
                logger.exception("Failed to unregister SIGINT wakeup fd")

        if self._notifier is not None:
            self._notifier.setEnabled(False)

        self.quit_requested.emit()

    def dispose(self) -> None:
        """Restore previous state, disable the notifier, and close fds.

        Idempotent and non-throwing: may be connected to ``aboutToQuit``.
        """
        if self._disposed:
            return
        self._disposed = True

        # Restore previous wakeup descriptor first.
        if self._wakeup_registered:
            try:
                signal.set_wakeup_fd(self._previous_wakeup_fd)
            except Exception:
                logger.exception("Failed to restore previous wakeup fd")
            self._wakeup_registered = False

        # Then restore previous SIGINT handler.
        if self._handler_installed:
            try:
                signal.signal(
                    signal.SIGINT,
                    self._previous_handler
                    if self._previous_handler is not None
                    else signal.SIG_DFL,
                )
            except Exception:
                logger.exception("Failed to restore previous SIGINT handler")
            self._handler_installed = False

        if self._notifier is not None:
            try:
                self._notifier.setEnabled(False)
                self._notifier.deleteLater()
            except Exception:
                logger.exception("Failed to disable notifier during disposal")
            self._notifier = None

        if self._read_fd != -1:
            try:
                os.close(self._read_fd)
            except Exception:
                logger.exception("Failed to close read pipe during disposal")
            self._read_fd = -1

        if self._write_fd != -1:
            try:
                os.close(self._write_fd)
            except Exception:
                logger.exception("Failed to close write pipe during disposal")
            self._write_fd = -1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", action="store_true", help="Run in test mode (record for 3s and exit)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    app = QApplication(sys.argv)
    app.setWindowIcon(load_app_icon())

    window = MainWindow()
    window.showMaximized()

    bridge = SigintBridge()
    bridge.quit_requested.connect(window.request_quit)
    app.aboutToQuit.connect(bridge.dispose)

    if args.test:
        logger.info("Running in test mode...")
        # Wait for devices to load
        QTimer.singleShot(1000, lambda: start_test(window, app))

    sys.exit(app.exec())


def start_test(window, app):
    logger.info("Test: Starting recording...")
    if window.middle_panel.record_btn.isEnabled():
        window.toggle_recording()
        # Stop after 3 seconds
        QTimer.singleShot(3000, lambda: stop_test(window, app))
    else:
        logger.warning("Test: Record button disabled (no devices?), exiting.")
        window.request_quit()


def stop_test(window, app):
    logger.info("Test: Stopping recording...")
    if window.middle_panel.is_recording:
        window.toggle_recording()
    logger.info("Test: Exiting...")
    window.request_quit()


if __name__ == "__main__":
    main()
