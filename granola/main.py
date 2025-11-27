import sys
import argparse
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from granola.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", action="store_true", help="Run in test mode (record for 3s and exit)"
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    if args.test:
        print("Running in test mode...")
        # Wait for devices to load
        QTimer.singleShot(1000, lambda: start_test(window, app))

    sys.exit(app.exec())


def start_test(window, app):
    print("Test: Starting recording...")
    if window.record_btn.isEnabled():
        window.toggle_recording()
        # Stop after 3 seconds
        QTimer.singleShot(3000, lambda: stop_test(window, app))
    else:
        print("Test: Record button disabled (no devices?), exiting.")
        app.quit()


def stop_test(window, app):
    print("Test: Stopping recording...")
    window.toggle_recording()
    print("Test: Exiting...")
    app.quit()


if __name__ == "__main__":
    main()
