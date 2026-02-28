import logging
import os

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from quinoa.calendar import authenticate, get_user_email, is_authenticated, logout
from quinoa.config import config

logger = logging.getLogger("quinoa")


class SettingsDialog(QDialog):
    # Emitted when calendar connection status changes
    calendar_connected = pyqtSignal()
    calendar_disconnected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # API Key
        self.api_key_edit = QLineEdit(config.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Paste your Gemini API Key here")
        form.addRow("Gemini API Key:", self.api_key_edit)

        # Output Directory
        self.output_dir_edit = QLineEdit(config.get("output_dir", ""))
        self.output_dir_btn = QPushButton("Browse...")
        self.output_dir_btn.clicked.connect(self.browse_output_dir)
        form.addRow("Recordings Path:", self.output_dir_edit)
        form.addRow("", self.output_dir_btn)

        layout.addLayout(form)

        # File Search settings group
        file_search_group = QGroupBox("AI Assistant")
        file_search_layout = QVBoxLayout(file_search_group)

        self.file_search_checkbox = QCheckBox("Enable AI search across meetings")
        self.file_search_checkbox.setChecked(config.get("file_search_enabled", False))
        file_search_layout.addWidget(self.file_search_checkbox)

        file_search_info = QLabel(
            "When enabled, your meeting transcripts and notes are synced to\n"
            "Gemini File Search for AI-powered search. This allows you to ask\n"
            "questions about your past meetings in the AI Assistant panel.\n\n"
            "Note: Requires app restart to take effect."
        )
        file_search_info.setStyleSheet("color: #888; font-size: 11px;")
        file_search_layout.addWidget(file_search_info)

        layout.addWidget(file_search_group)

        # Automation settings group
        automation_group = QGroupBox("Automation")
        automation_layout = QVBoxLayout(automation_group)

        self.auto_transcribe_checkbox = QCheckBox("Auto-transcribe after recording stops")
        self.auto_transcribe_checkbox.setChecked(config.get("auto_transcribe", True))
        automation_layout.addWidget(self.auto_transcribe_checkbox)

        auto_transcribe_info = QLabel(
            "When enabled, recordings are automatically sent to Gemini\n"
            "for transcription as soon as you stop recording."
        )
        auto_transcribe_info.setStyleSheet("color: #888; font-size: 11px;")
        automation_layout.addWidget(auto_transcribe_info)

        layout.addWidget(automation_group)

        # Notification settings group
        notification_group = QGroupBox("Notifications")
        notification_layout = QVBoxLayout(notification_group)

        self.notifications_checkbox = QCheckBox("Show meeting notifications")
        self.notifications_checkbox.setChecked(config.get("notifications_enabled", True))
        notification_layout.addWidget(self.notifications_checkbox)

        self.recording_reminder_checkbox = QCheckBox("Remind me to record when a meeting starts")
        self.recording_reminder_checkbox.setChecked(config.get("recording_reminder_enabled", True))
        notification_layout.addWidget(self.recording_reminder_checkbox)

        self.notify_video_only_checkbox = QCheckBox(
            "Only notify for meetings with video links (Meet/Zoom/Teams)"
        )
        self.notify_video_only_checkbox.setChecked(config.get("notify_video_only", True))
        notification_layout.addWidget(self.notify_video_only_checkbox)

        # Grace period row
        grace_row = QHBoxLayout()
        grace_row.addWidget(QLabel("Recording reminder delay:"))
        self.grace_period_spin = QSpinBox()
        self.grace_period_spin.setRange(0, 30)
        self.grace_period_spin.setSuffix(" min")
        self.grace_period_spin.setValue(config.get("reminder_grace_period_minutes", 2))
        grace_row.addWidget(self.grace_period_spin)
        grace_row.addStretch()
        notification_layout.addLayout(grace_row)

        notification_info = QLabel(
            "Notifications require Google Calendar to be connected.\n"
            "Recording reminders appear after the selected delay once a meeting starts\n"
            "and you haven't begun recording yet."
        )
        notification_info.setStyleSheet("color: #888; font-size: 11px;")
        notification_layout.addWidget(notification_info)

        layout.addWidget(notification_group)

        # Google Calendar settings group
        calendar_group = QGroupBox("Google Calendar")
        calendar_layout = QVBoxLayout(calendar_group)

        # Connection status row
        status_row = QHBoxLayout()
        self.calendar_status_label = QLabel()
        status_row.addWidget(self.calendar_status_label)
        status_row.addStretch()

        self.calendar_connect_btn = QPushButton()
        self.calendar_connect_btn.clicked.connect(self._on_calendar_btn_clicked)
        status_row.addWidget(self.calendar_connect_btn)

        calendar_layout.addLayout(status_row)

        calendar_info = QLabel(
            "Connect your Google Calendar to see upcoming meetings\n"
            "and automatically link recordings to calendar events."
        )
        calendar_info.setStyleSheet("color: #888; font-size: 11px;")
        calendar_layout.addWidget(calendar_info)

        layout.addWidget(calendar_group)

        # Update calendar UI state
        self._update_calendar_status()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Recordings Directory", self.output_dir_edit.text()
        )
        if path:
            self.output_dir_edit.setText(path)

    def save_settings(self):
        api_key = self.api_key_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()

        # Validation
        if not api_key:
            QMessageBox.warning(self, "Invalid Input", "API Key cannot be empty.")
            return

        if not output_dir:
            QMessageBox.warning(self, "Invalid Input", "Output directory cannot be empty.")
            return

        # Check if output directory exists or can be created
        try:
            os.makedirs(output_dir, exist_ok=True)
            # Check writability
            test_file = os.path.join(output_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            QMessageBox.warning(self, "Invalid Input", f"Output directory is not writable:\n{e}")
            return

        config.set("api_key", api_key)
        config.set("output_dir", output_dir)
        config.set("file_search_enabled", self.file_search_checkbox.isChecked())
        config.set("auto_transcribe", self.auto_transcribe_checkbox.isChecked())
        config.set("notifications_enabled", self.notifications_checkbox.isChecked())
        config.set("recording_reminder_enabled", self.recording_reminder_checkbox.isChecked())
        config.set("notify_video_only", self.notify_video_only_checkbox.isChecked())
        config.set("reminder_grace_period_minutes", self.grace_period_spin.value())
        self.accept()

    def _update_calendar_status(self) -> None:
        """Update the calendar connection status UI."""
        if is_authenticated():
            email = get_user_email()
            if email:
                self.calendar_status_label.setText(f"Connected as {email}")
                self.calendar_status_label.setStyleSheet("color: #4CAF50;")  # Green
                self.calendar_connect_btn.setText("Disconnect")
                return

        # If we get here, either we aren't authenticated or get_user_email failed
        if config.get("calendar_auth_expired", False):
            self.calendar_status_label.setText("Authentication expired")
            self.calendar_status_label.setStyleSheet("color: #f44336;")  # Red
        else:
            self.calendar_status_label.setText("Not connected")
            self.calendar_status_label.setStyleSheet("color: #888;")

        self.calendar_connect_btn.setText("Connect Calendar")

    def _on_calendar_btn_clicked(self) -> None:
        """Handle calendar connect/disconnect button click."""
        if is_authenticated():
            # Confirm disconnect
            reply = QMessageBox.question(
                self,
                "Disconnect Calendar",
                "Are you sure you want to disconnect your Google Calendar?\n\n"
                "Your calendar events will be cleared from the local database.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                logout()
                self._update_calendar_status()
                self.calendar_disconnected.emit()
                logger.info("Calendar disconnected")
        else:
            # Start OAuth flow
            self.calendar_connect_btn.setEnabled(False)
            self.calendar_connect_btn.setText("Connecting...")

            try:
                creds = authenticate()
                if creds:
                    self._update_calendar_status()
                    self.calendar_connected.emit()
                    QMessageBox.information(
                        self,
                        "Success",
                        "Google Calendar connected successfully!\n\n"
                        "Your upcoming meetings will appear in the left panel.",
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Connection Failed",
                        "Failed to connect to Google Calendar.\nPlease try again.",
                    )
            except Exception as e:
                logger.error("Calendar connection failed: %s", e)
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to connect to Google Calendar:\n{e}",
                )
            finally:
                self._update_calendar_status()
