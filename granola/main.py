import argparse
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from granola.logging import logger, setup_logging
from granola.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", action="store_true", help="Run in test mode (record for 3s and exit)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

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
        app.quit()


def stop_test(window, app):
    logger.info("Test: Stopping recording...")
    window.toggle_recording()
    logger.info("Test: Exiting...")
    app.quit()


if __name__ == "__main__":
    main()
