import logging
import os
import re

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from quinoa.constants import GEMINI_AVAILABLE_MODELS, GEMINI_MODEL_TRANSCRIPTION

logger = logging.getLogger("quinoa")

# Keywords that indicate a model is not suitable for transcription
_MODEL_EXCLUDE_KEYWORDS = [
    "image",
    "tts",
    "gemma",
    "robotics",
    "computer-use",
    "deep-research",
    "nano-banana",
    "customtools",
]

# Pattern for version-pinned model names (e.g. gemini-2.0-flash-001)
_VERSION_PIN_RE = re.compile(r"-\d{3}$")


def filter_gemini_models(models: list[dict[str, object]]) -> list[str]:
    """Filter raw model list to models suitable for Quinoa.

    Args:
        models: List of dicts with 'name' and 'supported_actions' keys.

    Returns:
        Sorted list of short model names (without 'models/' prefix).
    """
    result: list[str] = []
    for m in models:
        name = str(m.get("name", ""))
        actions = m.get("supported_actions") or []
        if not isinstance(actions, list):
            continue

        # Must support generateContent
        if "generateContent" not in actions:
            continue

        # Must be a Gemini model
        if not name.startswith("models/gemini-"):
            continue

        short = name.removeprefix("models/")

        # Exclude specialized / non-transcription models
        if any(kw in short for kw in _MODEL_EXCLUDE_KEYWORDS):
            continue

        # Exclude version-pinned variants (e.g. gemini-2.0-flash-001)
        if _VERSION_PIN_RE.search(short):
            continue

        # Exclude 'latest' aliases (redundant with canonical names)
        if short.endswith("-latest"):
            continue

        result.append(short)

    # Sort: non-preview first, then alphabetically descending (newest first)
    def sort_key(name: str) -> tuple[int, str]:
        # 0 for preview (sorted last), 1 for non-preview (sorted first)
        # reverse=True makes higher values come first
        is_stable = 0 if "preview" in name else 1
        return (is_stable, name)

    result.sort(key=sort_key, reverse=True)
    return result


class _ModelFetchWorker(QThread):
    """Background worker to fetch available Gemini models from the API."""

    models_fetched = pyqtSignal(list)  # list[str]

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    def run(self) -> None:
        try:
            from google import genai

            client = genai.Client(api_key=self._api_key)
            raw_models = list(client.models.list())

            model_dicts: list[dict[str, object]] = [
                {
                    "name": m.name,
                    "supported_actions": m.supported_actions,
                }
                for m in raw_models
            ]
            filtered = filter_gemini_models(model_dicts)

            if filtered:
                self.models_fetched.emit(filtered)
                logger.debug("Fetched %d Gemini models from API", len(filtered))
        except Exception as e:
            logger.debug("Failed to fetch model list from API: %s", e)


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

        # Gemini Model selector
        self.model_combo = QComboBox()
        initial_models = config.get("cached_gemini_models") or GEMINI_AVAILABLE_MODELS
        self.model_combo.addItems(initial_models)
        current_model = config.get("gemini_model") or GEMINI_MODEL_TRANSCRIPTION
        idx = self.model_combo.findText(current_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        form.addRow("Gemini Model:", self.model_combo)

        # Kick off background model list refresh
        self._model_worker: _ModelFetchWorker | None = None
        api_key = config.get("api_key", "")
        if api_key:
            self._model_worker = _ModelFetchWorker(api_key)
            self._model_worker.models_fetched.connect(self._on_models_fetched)
            self._model_worker.start()

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
        config.set("gemini_model", self.model_combo.currentText())
        config.set("file_search_enabled", self.file_search_checkbox.isChecked())
        config.set("auto_transcribe", self.auto_transcribe_checkbox.isChecked())
        config.set("notifications_enabled", self.notifications_checkbox.isChecked())
        config.set("recording_reminder_enabled", self.recording_reminder_checkbox.isChecked())
        config.set("notify_video_only", self.notify_video_only_checkbox.isChecked())
        config.set("reminder_grace_period_minutes", self.grace_period_spin.value())
        self.accept()

    def _on_models_fetched(self, models: list[str]) -> None:
        """Update the model combo box with freshly fetched models."""
        current_selection = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)

        # Restore selection
        idx = self.model_combo.findText(current_selection)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

        # Cache for next time
        config.set("cached_gemini_models", models)

    def closeEvent(self, a0) -> None:
        """Clean up background worker on dialog close."""
        if self._model_worker and self._model_worker.isRunning():
            self._model_worker.quit()
            self._model_worker.wait(2000)
        super().closeEvent(a0)

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
