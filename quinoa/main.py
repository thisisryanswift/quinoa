import argparse
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from quinoa.compatibility import get_distro_name, is_pipewire_installed, is_pipewire_running
from quinoa.logging import logger, setup_logging


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", action="store_true", help="Run in test mode (record for 3s and exit)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    app = QApplication(sys.argv)

    # Check for PipeWire availability
    if not is_pipewire_running():
        msg = "PipeWire audio service is not running."
        info = "Quinoa requires PipeWire for audio recording."

        if not is_pipewire_installed():
            info += "\n\nPipeWire does not appear to be installed."
            distro = get_distro_name()
            if "Ubuntu" in distro:
                info += "\nOn Ubuntu 22.04 or earlier, you may need to install 'pipewire' and 'pipewire-pulse'."
        else:
            info += "\n\nPipeWire is installed but the service is not active."
            info += "\nTry running: systemctl --user start pipewire"

        # If in test mode, just log it. If interactive, show warning.
        if args.test:
            logger.warning(f"{msg} {info}")
        else:
            mbox = QMessageBox()
            mbox.setIcon(QMessageBox.Icon.Warning)
            mbox.setWindowTitle("PipeWire Missing")
            mbox.setText(msg)
            mbox.setInformativeText(info)
            mbox.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            ret = mbox.exec()
            if ret == QMessageBox.StandardButton.Cancel:
                sys.exit(1)

    try:
        from quinoa.ui.main_window import MainWindow
    except ImportError as e:
        logger.error(f"Failed to load application: {e}")
        if "libpipewire" in str(e) or "quinoa_audio" in str(e):
            mbox = QMessageBox()
            mbox.setIcon(QMessageBox.Icon.Critical)
            mbox.setWindowTitle("Dependency Error")
            mbox.setText("Failed to load audio component.")
            info = f"Error: {e}\n\nThis usually means the PipeWire shared libraries are missing."
            distro = get_distro_name()
            if "Ubuntu" in distro:
                info += "\n\nOn Ubuntu, try installing: libpipewire-0.3-0 or libpipewire-0.3-dev"
            mbox.setInformativeText(info)
            mbox.exec()
            sys.exit(1)
        raise

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
