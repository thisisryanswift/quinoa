"""Record tab UI and functionality."""

import logging
import os
import shutil
import time
from collections.abc import Callable
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import quinoa_audio
from quinoa.config import config
from quinoa.constants import (
    DEFAULT_SAMPLE_RATE,
    LAYOUT_MARGIN,
    LAYOUT_SPACING,
    MIN_DISK_SPACE_BYTES,
    TIMER_INTERVAL_MS,
)
from quinoa.storage.database import Database
from quinoa.ui.settings_dialog import SettingsDialog
from quinoa.ui.styles import (
    BUTTON_PAUSE,
    BUTTON_RECORD,
    BUTTON_STOP,
    LEVEL_METER_MIC,
    LEVEL_METER_SYSTEM,
    STATUS_LABEL,
    STATUS_LABEL_PAUSED,
    TITLE_LABEL,
)
from quinoa.ui.transcribe_worker import TranscribeWorker
from quinoa.ui.transcript_handler import (
    format_transcript_display,
    parse_transcription_result,
)

logger = logging.getLogger("quinoa")


class RecordTab:
    """Manages the record tab UI and recording functionality."""

    def __init__(
        self,
        parent_window: QWidget,
        db: Database,
        on_recording_state_changed: Callable[[bool], None] | None = None,
        on_history_changed: Callable[[], None] | None = None,
    ):
        self.parent = parent_window
        self.db = db
        self.on_recording_state_changed = on_recording_state_changed
        self.on_history_changed = on_history_changed

        # Recording state
        self.recording_session = None
        self.recording_start_time = 0.0
        self.recording_paused_time = 0.0
        self.pause_start_time = 0.0
        self.is_paused = False
        self.current_session_dir: str | None = None
        self.current_rec_id: str | None = None
        self.devices: list = []

        # Device monitoring
        self.device_monitor = None

        # Timer for UI updates
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_timer)

        # Transcription worker
        self._worker: TranscribeWorker | None = None

        # UI components - initialized in setup(), accessed after
        self.mic_combo: QComboBox
        self.mic_level_bar: QProgressBar
        self.sys_audio_check: QCheckBox
        self.sys_level_bar: QProgressBar
        self.status_label: QLabel
        self.record_btn: QPushButton
        self.pause_btn: QPushButton
        self.transcribe_btn: QPushButton
        self.transcript_area: QTextEdit

    def setup(self, parent: QWidget):
        """Setup the record tab UI."""
        layout = QVBoxLayout(parent)
        layout.setSpacing(LAYOUT_SPACING)
        layout.setContentsMargins(LAYOUT_MARGIN, LAYOUT_MARGIN, LAYOUT_MARGIN, LAYOUT_MARGIN)

        # Title
        title_label = QLabel("New Recording")
        title_label.setStyleSheet(TITLE_LABEL)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Device Selection
        dev_layout = QVBoxLayout()
        dev_layout.addWidget(QLabel("Microphone:"))
        self.mic_combo = QComboBox()
        dev_layout.addWidget(self.mic_combo)

        # Mic Level Meter
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setStyleSheet(LEVEL_METER_MIC)
        dev_layout.addWidget(self.mic_level_bar)

        layout.addLayout(dev_layout)

        # System Audio Checkbox
        sys_layout = QVBoxLayout()
        self.sys_audio_check = QCheckBox("Record System Audio")
        self.sys_audio_check.setChecked(True)
        sys_layout.addWidget(self.sys_audio_check)

        # System Level Meter
        self.sys_level_bar = QProgressBar()
        self.sys_level_bar.setRange(0, 100)
        self.sys_level_bar.setTextVisible(False)
        self.sys_level_bar.setStyleSheet(LEVEL_METER_SYSTEM)
        sys_layout.addWidget(self.sys_level_bar)
        layout.addLayout(sys_layout)

        # Status/Timer
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(STATUS_LABEL)
        layout.addWidget(self.status_label)

        # Record and Pause Buttons
        button_layout = QHBoxLayout()

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(50)
        self.record_btn.setStyleSheet(BUTTON_RECORD)
        self.record_btn.clicked.connect(self.toggle_recording)
        button_layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumHeight(50)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet(BUTTON_PAUSE)
        self.pause_btn.clicked.connect(self.toggle_pause)
        button_layout.addWidget(self.pause_btn)

        layout.addLayout(button_layout)

        # Transcribe Button
        self.transcribe_btn = QPushButton("Transcribe Last Recording")
        self.transcribe_btn.setMinimumHeight(40)
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self._start_transcription)
        layout.addWidget(self.transcribe_btn)

        # Settings Button
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)

        # Transcript Area
        layout.addWidget(QLabel("Transcript:"))
        self.transcript_area = QTextEdit()
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setPlaceholderText("Transcript will appear here...")
        layout.addWidget(self.transcript_area)

        # Initialize devices
        self.refresh_devices()

        # Start device monitoring
        self._start_device_monitor()

    def _start_device_monitor(self):
        """Start monitoring for device changes."""
        try:
            self.device_monitor = quinoa_audio.subscribe_device_changes()
        except Exception as e:
            logger.warning("Failed to start device monitor: %s", e)

    def stop_device_monitor(self):
        """Stop the device monitor."""
        if self.device_monitor:
            try:
                self.device_monitor.stop()
            except Exception as e:
                logger.warning("Error stopping device monitor: %s", e)

    def refresh_devices(self):
        """Refresh the list of available audio devices."""
        self.mic_combo.clear()
        try:
            self.devices = quinoa_audio.list_devices()
            default_index = 0

            for device in self.devices:
                if device.device_type == quinoa_audio.DeviceType.Microphone:
                    self.mic_combo.addItem(f"{device.name}", device.id)
                    if device.is_default:
                        default_index = self.mic_combo.count() - 1

            if self.mic_combo.count() > 0:
                self.mic_combo.setCurrentIndex(default_index)
                self.record_btn.setEnabled(True)
            else:
                self.mic_combo.addItem("No microphones found", None)
                self.record_btn.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to list devices: {str(e)}")
            self.record_btn.setEnabled(False)

    def _open_settings(self):
        """Open the settings dialog."""
        dialog = SettingsDialog(self.parent)
        dialog.exec()

    def _check_disk_space(self) -> bool:
        """Check if there's enough disk space for recording."""
        output_dir = config.get("output_dir")
        if not output_dir:
            return False

        try:
            if not os.path.exists(output_dir):
                return True  # Will be created
            total, used, free = shutil.disk_usage(output_dir)
            if free < MIN_DISK_SPACE_BYTES:
                QMessageBox.warning(
                    self.parent,
                    "Low Disk Space",
                    f"Only {free // (1024 * 1024)} MB free in {output_dir}.",
                )
                return False
        except Exception as e:
            logger.warning("Failed to check disk space: %s", e)
        return True

    def toggle_recording(self):
        """Toggle between start and stop recording."""
        if self.recording_session:
            self._stop_recording()
        else:
            self._start_recording()

    def toggle_pause(self):
        """Toggle between pause and resume."""
        if not self.recording_session:
            return

        try:
            if self.is_paused:
                self.recording_session.resume()
            else:
                self.recording_session.pause()
        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to toggle pause: {str(e)}")

    def _start_recording(self):
        """Start a new recording session."""
        mic_id = self.mic_combo.currentData()
        if not mic_id:
            QMessageBox.warning(self.parent, "Warning", "Please select a microphone.")
            return

        # Check for Bluetooth A2DP profile
        for device in self.devices:
            if device.id == mic_id and device.is_bluetooth:
                profile = getattr(device, "bluetooth_profile", None)
                if profile and "a2dp" in profile.lower():
                    reply = QMessageBox.warning(
                        self.parent,
                        "Bluetooth Warning",
                        f"The device '{device.name}' appears to be in A2DP (Music) mode.\n"
                        "Microphone input may not work or may be silent.\n\n"
                        "Do you want to continue anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.No:
                        return

        if not self._check_disk_space():
            return

        try:
            # Generate Session ID and Directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_rec_id = f"rec_{timestamp}"

            base_dir = config.get("output_dir")
            if not base_dir:
                QMessageBox.critical(self.parent, "Error", "Output directory not set.")
                return

            self.current_session_dir = os.path.join(base_dir, self.current_rec_id)
            os.makedirs(self.current_session_dir, exist_ok=True)

            config_obj = quinoa_audio.RecordingConfig(
                output_dir=self.current_session_dir,
                mic_device_id=mic_id,
                system_audio=self.sys_audio_check.isChecked(),
                sample_rate=DEFAULT_SAMPLE_RATE,
            )

            self.recording_session = quinoa_audio.start_recording(config_obj)
            self.recording_start_time = time.time()
            self.recording_paused_time = 0
            self.is_paused = False

            # Add to DB
            mic_name = self.mic_combo.currentText()
            self.db.add_recording(
                self.current_rec_id,
                f"Recording {timestamp}",
                datetime.now(),
                os.path.join(self.current_session_dir, "microphone.wav"),
                os.path.join(self.current_session_dir, "system.wav"),
                mic_device_id=mic_id,
                mic_device_name=mic_name,
                directory_path=self.current_session_dir,
            )
            if self.on_history_changed:
                self.on_history_changed()

            # Update UI
            self.record_btn.setText("Stop Recording")
            self.record_btn.setStyleSheet(BUTTON_STOP)
            self.mic_combo.setEnabled(False)
            self.sys_audio_check.setEnabled(False)
            self.transcribe_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.status_label.setText("Recording...")

            # Notify state change
            if self.on_recording_state_changed:
                self.on_recording_state_changed(True)

            self.timer.start(TIMER_INTERVAL_MS)

        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to start recording: {str(e)}")

    def _stop_recording(self):
        """Stop the current recording session."""
        if self.recording_session:
            try:
                self.recording_session.stop()
            except Exception as e:
                logger.error("Error stopping session: %s", e)

            # Update DB
            duration = time.time() - self.recording_start_time - self.recording_paused_time
            self.db.update_recording_status(
                self.current_rec_id,
                "completed",
                duration=duration,
                ended_at=datetime.now(),
            )
            if self.on_history_changed:
                self.on_history_changed()

            self.recording_session = None
            self.timer.stop()

            # Reset meters
            self.mic_level_bar.setValue(0)
            self.sys_level_bar.setValue(0)

            # Update UI
            self.record_btn.setText("Start Recording")
            self.record_btn.setStyleSheet(BUTTON_RECORD)
            self.mic_combo.setEnabled(True)
            self.sys_audio_check.setEnabled(True)
            self.transcribe_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("Pause")
            self.is_paused = False
            if self.current_session_dir:
                self.status_label.setText("Saved to " + self.current_session_dir)
            else:
                self.status_label.setText("Recording stopped")

            # Notify state change
            if self.on_recording_state_changed:
                self.on_recording_state_changed(False)

    def _handle_audio_error(self, error_msg: str):
        """Handle audio errors with user-friendly messages."""
        friendly_msg = error_msg
        title = "Audio Error"

        if "PipeWire" in error_msg:
            if "connection" in error_msg.lower() or "connect" in error_msg.lower():
                friendly_msg = (
                    "Lost connection to the audio server (PipeWire).\n"
                    "Please check your audio settings or restart the application."
                )
            else:
                friendly_msg = f"Audio server error: {error_msg}"
        elif "device" in error_msg.lower() and "not found" in error_msg.lower():
            friendly_msg = (
                "The selected microphone could not be found.\nIt may have been unplugged."
            )

        logger.error("Audio Error: %s", error_msg)
        self.status_label.setText("Error occurred")
        QMessageBox.critical(self.parent, title, friendly_msg)

    def _update_timer(self):
        """Update the timer display and poll for events."""
        if self.recording_session:
            # Calculate elapsed time (excluding paused time)
            if self.is_paused:
                current_pause_duration = time.time() - self.pause_start_time
                elapsed = (
                    time.time()
                    - self.recording_start_time
                    - self.recording_paused_time
                    - current_pause_duration
                )
            else:
                elapsed = time.time() - self.recording_start_time - self.recording_paused_time

            mins = int(elapsed // 60)
            secs = int(elapsed % 60)

            if self.is_paused:
                self.status_label.setText(f"Paused: {mins:02d}:{secs:02d}")
            else:
                self.status_label.setText(f"Recording: {mins:02d}:{secs:02d}")

            # Poll recording events
            try:
                events = self.recording_session.poll_events()
                for event in events:
                    if event.type_ == "levels":
                        if event.mic_level is not None:
                            val = int(event.mic_level * 100)
                            self.mic_level_bar.setValue(min(100, val))
                        if event.system_level is not None:
                            val = int(event.system_level * 100)
                            self.sys_level_bar.setValue(min(100, val))
                    elif event.type_ == "paused":
                        self.is_paused = True
                        self.pause_start_time = time.time()
                        self.pause_btn.setText("Resume")
                        self.status_label.setStyleSheet(STATUS_LABEL_PAUSED)
                    elif event.type_ == "resumed":
                        self.is_paused = False
                        self.recording_paused_time += time.time() - self.pause_start_time
                        self.pause_btn.setText("Pause")
                        self.status_label.setStyleSheet(STATUS_LABEL)
                    elif event.type_ == "stopped":
                        self._stop_recording()
                    elif event.type_ == "error":
                        self._handle_audio_error(event.message)
                    elif event.type_ == "pipewire_disconnected":
                        self.status_label.setText("Connection lost - Reconnecting...")
                        self.status_label.setStyleSheet(STATUS_LABEL_PAUSED)
                    elif event.type_ == "started":
                        self.status_label.setText("Recording...")
                        self.status_label.setStyleSheet(STATUS_LABEL)
            except Exception as e:
                logger.error("Error polling events: %s", e)

        # Poll device monitor for hot-plug events
        if self.device_monitor:
            try:
                device_events = self.device_monitor.poll()
                for event in device_events:
                    if event.type_ in ["added", "removed"]:
                        logger.info(
                            "Device %s: %s (%s)",
                            event.type_,
                            event.device_name,
                            event.device_id,
                        )
                        self.refresh_devices()
                        break  # Only refresh once per timer tick
            except Exception as e:
                logger.error("Error polling device events: %s", e)

    def _start_transcription(self):
        """Start transcription of the last recording."""
        if not config.get("api_key"):
            QMessageBox.warning(
                self.parent, "Missing API Key", "Please set your Gemini API Key in Settings."
            )
            self._open_settings()
            return

        if not self.current_session_dir:
            return

        self.transcribe_btn.setEnabled(False)
        self.status_label.setText("Transcribing...")
        self.transcript_area.setText("Processing audio and sending to Gemini...")

        self._worker = TranscribeWorker(self.current_session_dir)
        self._worker.finished.connect(self._on_transcription_finished)
        self._worker.error.connect(self._on_transcription_error)
        self._worker.start()

    def _on_transcription_finished(self, json_str: str):
        """Handle successful transcription."""
        self.status_label.setText("Transcription Complete")
        self.transcribe_btn.setEnabled(True)

        result = parse_transcription_result(json_str)

        # Display transcript
        display_text = format_transcript_display(result["transcript"], result["summary"])
        self.transcript_area.setText(display_text)

        # Save to DB
        if self.current_rec_id:
            self.db.save_transcript(self.current_rec_id, result["transcript"], result["summary"])
            if not result["parse_error"]:
                self.db.save_action_items(self.current_rec_id, result["action_items"])
            if self.on_history_changed:
                self.on_history_changed()

    def _on_transcription_error(self, error_msg: str):
        """Handle transcription error."""
        self.status_label.setText("Transcription Failed")
        self.transcript_area.setText(f"Error: {error_msg}")
        self.transcribe_btn.setEnabled(True)
        QMessageBox.warning(self.parent, "Transcription Error", error_msg)

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self.recording_session is not None
