import sys
import os
import time
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QCheckBox,
    QMessageBox,
    QTextEdit,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QSystemTrayIcon,
    QMenu,
    QApplication,
    QProgressBar,
    QInputDialog,
)
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QShortcut
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
import granola_audio
from granola.transcription.processor import create_stereo_mix
from granola.transcription.gemini import GeminiTranscriber
from granola.storage.database import Database
from granola.config import config
from granola.ui.settings_dialog import SettingsDialog


class TranscribeWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, output_dir):
        super().__init__()
        self.output_dir = output_dir

    def run(self):
        try:
            mic_path = os.path.join(self.output_dir, "microphone.wav")
            sys_path = os.path.join(self.output_dir, "system.wav")
            stereo_path = os.path.join(self.output_dir, "mixed_stereo.wav")

            # 1. Mix audio
            if not os.path.exists(mic_path):
                self.error.emit("Microphone recording not found.")
                return

            if os.path.exists(sys_path):
                create_stereo_mix(mic_path, sys_path, stereo_path)
                upload_path = stereo_path
            else:
                upload_path = mic_path

            # 2. Transcribe
            api_key = config.get("api_key")
            transcriber = GeminiTranscriber(api_key=api_key)
            transcript = transcriber.transcribe(upload_path)

            self.finished.emit(transcript)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Granola Linux")
        self.setMinimumSize(800, 600)

        self.db = Database()
        self.recording_session = None
        self.recording_start_time = 0
        self.recording_paused_time = 0  # Track time spent paused
        self.pause_start_time = 0  # When pause started
        self.is_paused = False
        self.current_session_dir = None
        self.current_rec_id = None
        self.selected_history_rec_id = None
        self.device_monitor = None

        # Main layout with Tabs
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        # Tab 1: Record
        record_widget = QWidget()
        self.setup_record_tab(record_widget)
        tabs.addTab(record_widget, "Record")

        # Tab 2: History
        history_widget = QWidget()
        self.setup_history_tab(history_widget)
        tabs.addTab(history_widget, "History")

        # Timer for updating UI during recording
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)

        # Initialize devices
        self.refresh_devices()

        # Setup Shortcuts
        self.setup_shortcuts()

        # Start device monitoring
        try:
            self.device_monitor = granola_audio.subscribe_device_changes()
        except Exception as e:
            print(f"Failed to start device monitor: {e}")

        # Setup Tray Icon
        self.setup_tray_icon()

    def setup_shortcuts(self):
        # Start/Stop Recording (Ctrl+R)
        self.record_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.record_shortcut.activated.connect(self.toggle_recording)

        # Pause/Resume (Space)
        self.pause_shortcut = QShortcut(QKeySequence("Space"), self)
        self.pause_shortcut.activated.connect(self.toggle_pause)

        # Quit (Ctrl+Q)
        self.quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.quit_shortcut.activated.connect(self.close)

    def setup_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("WARNING: System tray is not available on this system.")
            return

        self.tray_icon = QSystemTrayIcon(self)

        # Use a standard icon
        icon = self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay)
        if icon.isNull():
            print("WARNING: Standard icon SP_MediaPlay not found.")

        self.tray_icon.setIcon(icon)

        # Context Menu
        menu = QMenu()

        self.show_action = QAction("Show", self)
        self.show_action.triggered.connect(self.show)
        menu.addAction(self.show_action)

        self.tray_record_action = QAction("Start Recording", self)
        self.tray_record_action.triggered.connect(self.toggle_recording)
        menu.addAction(self.tray_record_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        print("System tray icon initialized.")

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()

    def closeEvent(self, event):
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
            self.tray_icon.showMessage(
                "Granola",
                "Application minimized to tray. Right-click icon to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        else:
            # Stop device monitor
            if self.device_monitor:
                try:
                    self.device_monitor.stop()
                except Exception as e:
                    print(f"Error stopping device monitor: {e}")
            event.accept()

    def setup_record_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title_label = QLabel("New Recording")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
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
        self.mic_level_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 3px;
                background-color: #eee;
                height: 10px;
            }
            QProgressBar::chunk {
                background-color: #2ecc71;
            }
        """)
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
        self.sys_level_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 3px;
                background-color: #eee;
                height: 10px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
            }
        """)
        sys_layout.addWidget(self.sys_level_bar)
        layout.addLayout(sys_layout)

        # Status/Timer
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; color: #666;")
        layout.addWidget(self.status_label)

        # Record and Pause Buttons
        button_layout = QHBoxLayout()

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(50)
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-size: 18px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        self.record_btn.clicked.connect(self.toggle_recording)
        button_layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumHeight(50)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #f39c12;
                color: white;
                font-size: 18px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e67e22;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.pause_btn.clicked.connect(self.toggle_pause)
        button_layout.addWidget(self.pause_btn)

        layout.addLayout(button_layout)

        # Transcribe Button
        self.transcribe_btn = QPushButton("Transcribe Last Recording")
        self.transcribe_btn.setMinimumHeight(40)
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self.start_transcription)
        layout.addWidget(self.transcribe_btn)

        # Settings Button
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_btn)

        # Transcript Area
        layout.addWidget(QLabel("Transcript:"))
        self.transcript_area = QTextEdit()
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setPlaceholderText("Transcript will appear here...")
        layout.addWidget(self.transcript_area)

    def setup_history_tab(self, parent):
        layout = QHBoxLayout(parent)

        # Splitter for list and details
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # List of recordings
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.addWidget(QLabel("Past Recordings:"))
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(
            self.show_history_context_menu
        )
        self.history_list.itemClicked.connect(self.load_history_item)
        list_layout.addWidget(self.history_list)
        splitter.addWidget(list_container)

        # Details view
        details_container = QWidget()
        details_layout = QVBoxLayout(details_container)

        # Tabs for Transcript / Action Items
        self.history_details_tabs = QTabWidget()

        # Transcript Tab
        self.history_transcript_edit = QTextEdit()
        self.history_transcript_edit.setReadOnly(True)
        self.history_details_tabs.addTab(self.history_transcript_edit, "Transcript")

        # Action Items Tab
        self.history_actions_list = QListWidget()
        self.history_details_tabs.addTab(self.history_actions_list, "Action Items")

        details_layout.addWidget(self.history_details_tabs)

        # Transcribe Button for History
        self.history_transcribe_btn = QPushButton("Transcribe")
        self.history_transcribe_btn.clicked.connect(
            self.transcribe_selected_history_item
        )
        self.history_transcribe_btn.setEnabled(False)
        details_layout.addWidget(self.history_transcribe_btn)

        splitter.addWidget(details_container)

        # Set initial sizes
        splitter.setSizes([300, 500])

        self.refresh_history()

    def show_history_context_menu(self, position):
        item = self.history_list.itemAt(position)
        if not item:
            return

        menu = QMenu()
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self.rename_recording(item))
        menu.addAction(rename_action)

        menu.exec(self.history_list.viewport().mapToGlobal(position))

    def rename_recording(self, item):
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        current_text = item.text().split("\n")[
            0
        ]  # Extract title from "Title (Duration)\nDate"
        # Remove duration if present
        if "(" in current_text:
            current_text = current_text.rsplit(" (", 1)[0]

        new_title, ok = QInputDialog.getText(
            self, "Rename Recording", "New Title:", text=current_text
        )

        if ok and new_title:
            try:
                self.db.update_recording_title(rec_id, new_title)
                self.refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to rename recording: {e}")

    def refresh_history(self):
        self.history_list.clear()
        try:
            recordings = self.db.get_recordings()
            for rec in recordings:
                # Format timestamp
                ts = rec["started_at"]
                try:
                    dt = datetime.fromisoformat(ts)
                    display_ts = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    display_ts = str(ts)

                # Format duration
                duration = rec["duration_seconds"]
                duration_str = ""
                if duration:
                    mins = int(duration // 60)
                    secs = int(duration % 60)
                    duration_str = f" ({mins:02d}:{secs:02d})"

                item = QListWidgetItem(f"{rec['title']}{duration_str}\n{display_ts}")
                item.setData(Qt.ItemDataRole.UserRole, rec["id"])
                self.history_list.addItem(item)
        except Exception as e:
            print(f"Error refreshing history: {e}")

    def load_history_item(self, item):
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self.selected_history_rec_id = rec_id

        transcript = self.db.get_transcript(rec_id)
        action_items = self.db.get_action_items(rec_id)

        if transcript:
            text = transcript["text"]
            if transcript["summary"]:
                text = f"## Summary\n{transcript['summary']}\n\n## Transcript\n{text}"
            self.history_transcript_edit.setText(text)
            self.history_transcribe_btn.setText("Re-transcribe")
        else:
            self.history_transcript_edit.setText(
                "No transcript available for this recording."
            )
            self.history_transcribe_btn.setText("Transcribe")

        self.history_actions_list.clear()
        if action_items:
            for action in action_items:
                label = f"{action['text']}"
                if action["assignee"]:
                    label += f" ({action['assignee']})"
                self.history_actions_list.addItem(label)
        else:
            self.history_actions_list.addItem("No action items found.")

        self.history_transcribe_btn.setEnabled(True)

    def transcribe_selected_history_item(self):
        if (
            not hasattr(self, "selected_history_rec_id")
            or not self.selected_history_rec_id
        ):
            return

        if not config.get("api_key"):
            QMessageBox.warning(
                self, "Missing API Key", "Please set your Gemini API Key in Settings."
            )
            self.open_settings()
            return

        # Get recording details to find path
        rec = self.db.get_recording(self.selected_history_rec_id)
        if not rec:
            QMessageBox.warning(self, "Error", "Recording not found in database.")
            return

        # Derive session directory from mic_path
        mic_path = rec["mic_path"]
        session_dir = os.path.dirname(mic_path)

        if not os.path.exists(session_dir):
            QMessageBox.warning(
                self, "Error", f"Recording directory not found: {session_dir}"
            )
            return

        self.history_transcribe_btn.setEnabled(False)
        self.history_transcribe_btn.setText("Transcribing...")
        self.history_transcript_edit.setText(
            "Processing audio and sending to Gemini..."
        )

        self.history_worker = TranscribeWorker(session_dir)
        self.history_worker.finished.connect(self.on_history_transcription_finished)
        self.history_worker.error.connect(self.on_history_transcription_error)
        self.history_worker.start()

    def on_history_transcription_finished(self, json_str):
        self.history_transcribe_btn.setText("Re-transcribe")
        self.history_transcribe_btn.setEnabled(True)

        try:
            data = json.loads(json_str)
            transcript_text = data.get("transcript", "")
            summary = data.get("summary", "")
            action_items = data.get("action_items", [])

            # Display transcript
            display_text = transcript_text
            if summary:
                display_text = (
                    f"## Summary\n{summary}\n\n## Transcript\n{transcript_text}"
                )
            self.history_transcript_edit.setText(display_text)

            # Display action items
            self.history_actions_list.clear()
            for action in action_items:
                label = f"{action['text']}"
                if action.get("assignee"):
                    label += f" ({action['assignee']})"
                self.history_actions_list.addItem(label)

            # Save to DB
            if hasattr(self, "selected_history_rec_id"):
                self.db.save_transcript(
                    self.selected_history_rec_id, transcript_text, summary
                )
                self.db.save_action_items(self.selected_history_rec_id, action_items)

        except json.JSONDecodeError:
            # Fallback
            self.history_transcript_edit.setText(json_str)
            if hasattr(self, "selected_history_rec_id"):
                self.db.save_transcript(self.selected_history_rec_id, json_str)

    def on_history_transcription_error(self, error_msg):
        self.history_transcribe_btn.setText("Transcribe")
        self.history_transcribe_btn.setEnabled(True)
        self.history_transcript_edit.setText(f"Error: {error_msg}")
        QMessageBox.warning(self, "Transcription Error", error_msg)

    def refresh_devices(self):
        self.mic_combo.clear()
        try:
            self.devices = granola_audio.list_devices()
            default_index = 0

            for device in self.devices:
                if device.device_type == granola_audio.DeviceType.Microphone:
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
            QMessageBox.critical(self, "Error", f"Failed to list devices: {str(e)}")
            self.record_btn.setEnabled(False)

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def check_disk_space(self):
        import shutil

        output_dir = config.get("output_dir")
        if not output_dir:
            return False

        try:
            if not os.path.exists(output_dir):
                return True  # Will be created
            total, used, free = shutil.disk_usage(output_dir)
            # Warn if less than 500MB
            if free < 500 * 1024 * 1024:
                QMessageBox.warning(
                    self,
                    "Low Disk Space",
                    f"Only {free // (1024 * 1024)} MB free in {output_dir}.",
                )
                return False
        except Exception as e:
            print(f"Failed to check disk space: {e}")
        return True

    def toggle_recording(self):
        if self.recording_session:
            self.stop_recording()
        else:
            self.start_recording()

    def toggle_pause(self):
        if not self.recording_session:
            return

        try:
            if self.is_paused:
                self.recording_session.resume()
                # Don't update UI here - wait for the event
            else:
                self.recording_session.pause()
                # Don't update UI here - wait for the event
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to toggle pause: {str(e)}")

    def start_recording(self):
        mic_id = self.mic_combo.currentData()
        if not mic_id:
            QMessageBox.warning(self, "Warning", "Please select a microphone.")
            return

        # Check for Bluetooth A2DP profile
        if hasattr(self, "devices"):
            for device in self.devices:
                if device.id == mic_id and device.is_bluetooth:
                    profile = getattr(device, "bluetooth_profile", None)
                    if profile and "a2dp" in profile.lower():
                        reply = QMessageBox.warning(
                            self,
                            "Bluetooth Warning",
                            f"The device '{device.name}' appears to be in A2DP (Music) mode.\n"
                            "Microphone input may not work or may be silent.\n\n"
                            "Do you want to continue anyway?",
                            QMessageBox.StandardButton.Yes
                            | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        if reply == QMessageBox.StandardButton.No:
                            return

        # Check disk space
        if not self.check_disk_space():
            return

        try:
            # Generate Session ID and Directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_rec_id = f"rec_{timestamp}"

            base_dir = config.get("output_dir")
            if not base_dir:
                QMessageBox.critical(self, "Error", "Output directory not set.")
                return

            self.current_session_dir = os.path.join(base_dir, self.current_rec_id)
            os.makedirs(self.current_session_dir, exist_ok=True)

            config_obj = granola_audio.RecordingConfig(
                output_dir=self.current_session_dir,
                mic_device_id=mic_id,
                system_audio=self.sys_audio_check.isChecked(),
                sample_rate=48000,
            )

            self.recording_session = granola_audio.start_recording(config_obj)
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
            self.refresh_history()

            self.record_btn.setText("Stop Recording")
            self.record_btn.setStyleSheet("""
                QPushButton {
                    background-color: #333;
                    color: white;
                    font-size: 18px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #555;
                }
            """)
            self.mic_combo.setEnabled(False)
            self.sys_audio_check.setEnabled(False)
            self.transcribe_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.status_label.setText("Recording...")

            # Update Tray
            self.tray_record_action.setText("Stop Recording")
            self.tray_icon.setIcon(
                self.style().standardIcon(self.style().StandardPixmap.SP_MediaStop)
            )

            self.timer.start(100)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start recording: {str(e)}")

    def stop_recording(self):
        if self.recording_session:
            try:
                self.recording_session.stop()
            except Exception as e:
                print(f"Error stopping session: {e}")

            # Update DB
            duration = (
                time.time() - self.recording_start_time - self.recording_paused_time
            )
            self.db.update_recording_status(
                self.current_rec_id,
                "completed",
                duration=duration,
                ended_at=datetime.now(),
            )
            self.refresh_history()

            self.recording_session = None
            self.timer.stop()

            # Reset meters
            self.mic_level_bar.setValue(0)
            self.sys_level_bar.setValue(0)

            self.record_btn.setText("Start Recording")
            self.record_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    font-size: 18px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """)
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

            # Update Tray
            self.tray_record_action.setText("Start Recording")
            self.tray_icon.setIcon(
                self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay)
            )

    def handle_audio_error(self, error_msg):
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
                "The selected microphone could not be found.\n"
                "It may have been unplugged."
            )

        print(f"Audio Error: {error_msg}")
        self.status_label.setText("Error occurred")
        QMessageBox.critical(self, title, friendly_msg)

    def update_timer(self):
        if self.recording_session:
            # Calculate elapsed time (excluding paused time)
            if self.is_paused:
                # Currently paused - don't update elapsed time
                elapsed = self.recording_start_time + self.recording_paused_time
                current_pause_duration = time.time() - self.pause_start_time
                elapsed = (
                    time.time()
                    - self.recording_start_time
                    - self.recording_paused_time
                    - current_pause_duration
                )
            else:
                elapsed = (
                    time.time() - self.recording_start_time - self.recording_paused_time
                )

            mins = int(elapsed // 60)
            secs = int(elapsed % 60)

            if self.is_paused:
                self.status_label.setText(f"⏸ Paused: {mins:02d}:{secs:02d}")
            else:
                self.status_label.setText(f"Recording: {mins:02d}:{secs:02d}")

            # Poll events
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
                        self.status_label.setStyleSheet(
                            "font-size: 16px; color: orange;"
                        )
                    elif event.type_ == "resumed":
                        self.is_paused = False
                        self.recording_paused_time += (
                            time.time() - self.pause_start_time
                        )
                        self.pause_btn.setText("Pause")
                        self.status_label.setStyleSheet("font-size: 16px; color: #666;")
                    elif event.type_ == "stopped":
                        self.stop_recording()
                    elif event.type_ == "error":
                        self.handle_audio_error(event.message)
                    elif event.type_ == "pipewire_disconnected":
                        self.status_label.setText("⚠️ Connection lost - Reconnecting...")
                        self.status_label.setStyleSheet(
                            "font-size: 16px; color: orange;"
                        )
                    elif event.type_ == "started":
                        self.status_label.setText("Recording...")
                        self.status_label.setStyleSheet("font-size: 16px; color: #666;")
            except Exception as e:
                print(f"Error polling events: {e}")

        # Poll device monitor for hot-plug events
        if self.device_monitor:
            try:
                device_events = self.device_monitor.poll()
                for event in device_events:
                    if event.type_ in ["added", "removed"]:
                        print(
                            f"Device {event.type_}: {event.device_name} ({event.device_id})"
                        )
                        self.refresh_devices()
                        break  # Only refresh once per timer tick
            except Exception as e:
                print(f"Error polling device events: {e}")

    def start_transcription(self):
        if not config.get("api_key"):
            QMessageBox.warning(
                self, "Missing API Key", "Please set your Gemini API Key in Settings."
            )
            self.open_settings()
            return

        if not self.current_session_dir:
            return

        self.transcribe_btn.setEnabled(False)
        self.status_label.setText("Transcribing...")
        self.transcript_area.setText("Processing audio and sending to Gemini...")

        self.worker = TranscribeWorker(self.current_session_dir)
        self.worker.finished.connect(self.on_transcription_finished)
        self.worker.error.connect(self.on_transcription_error)
        self.worker.start()

    def on_transcription_finished(self, json_str):
        self.status_label.setText("Transcription Complete")
        self.transcribe_btn.setEnabled(True)

        try:
            data = json.loads(json_str)
            transcript_text = data.get("transcript", "")
            summary = data.get("summary", "")
            action_items = data.get("action_items", [])

            # Display transcript
            display_text = transcript_text
            if summary:
                display_text = (
                    f"## Summary\n{summary}\n\n## Transcript\n{transcript_text}"
                )
            self.transcript_area.setText(display_text)

            # Save to DB
            if self.current_rec_id:
                self.db.save_transcript(self.current_rec_id, transcript_text, summary)
                self.db.save_action_items(self.current_rec_id, action_items)
                self.refresh_history()

        except json.JSONDecodeError:
            self.transcript_area.setText(json_str)
            if self.current_rec_id:
                self.db.save_transcript(self.current_rec_id, json_str)
                self.refresh_history()

    def on_transcription_error(self, error_msg):
        self.status_label.setText("Transcription Failed")
        self.transcript_area.setText(f"Error: {error_msg}")
        self.transcribe_btn.setEnabled(True)
        QMessageBox.warning(self, "Transcription Error", error_msg)
