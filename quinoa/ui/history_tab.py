"""History tab UI and functionality."""

import logging
import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from quinoa.config import config
from quinoa.constants import SPLITTER_DEFAULT_SIZES
from quinoa.storage.database import Database
from quinoa.ui.transcribe_worker import TranscribeWorker
from quinoa.ui.transcript_handler import (
    format_action_item,
    format_transcript_display,
    parse_transcription_result,
)

logger = logging.getLogger("quinoa")


class HistoryTab:
    """Manages the history tab UI and functionality."""

    def __init__(self, db: Database):
        self.db = db
        self.selected_rec_id: str | None = None
        self._worker: TranscribeWorker | None = None

        # UI components - initialized in setup(), accessed after
        self.history_list: QListWidget
        self.transcript_edit: QTextEdit
        self.actions_list: QListWidget
        self.transcribe_btn: QPushButton

    def setup(self, parent: QWidget):
        """Setup the history tab UI."""
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
        self.history_list.customContextMenuRequested.connect(self._show_context_menu)
        self.history_list.itemClicked.connect(self._load_item)
        list_layout.addWidget(self.history_list)
        splitter.addWidget(list_container)

        # Details view
        details_container = QWidget()
        details_layout = QVBoxLayout(details_container)

        # Tabs for Transcript / Action Items
        details_tabs = QTabWidget()

        # Transcript Tab
        self.transcript_edit = QTextEdit()
        self.transcript_edit.setReadOnly(True)
        details_tabs.addTab(self.transcript_edit, "Transcript")

        # Action Items Tab
        self.actions_list = QListWidget()
        details_tabs.addTab(self.actions_list, "Action Items")

        details_layout.addWidget(details_tabs)

        # Transcribe Button
        self.transcribe_btn = QPushButton("Transcribe")
        self.transcribe_btn.clicked.connect(self._transcribe_selected)
        self.transcribe_btn.setEnabled(False)
        details_layout.addWidget(self.transcribe_btn)

        splitter.addWidget(details_container)

        # Set initial sizes
        splitter.setSizes(SPLITTER_DEFAULT_SIZES)

        self.refresh()

    def _show_context_menu(self, position):
        """Show context menu for history item."""
        item = self.history_list.itemAt(position)
        if not item:
            return

        menu = QMenu()
        rename_action = QAction("Rename", self.history_list)
        rename_action.triggered.connect(lambda: self._rename_recording(item))
        menu.addAction(rename_action)

        menu.exec(self.history_list.viewport().mapToGlobal(position))

    def _rename_recording(self, item: QListWidgetItem):
        """Rename a recording."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        current_text = item.text().split("\n")[0]  # Extract title
        # Remove duration if present
        if "(" in current_text:
            current_text = current_text.rsplit(" (", 1)[0]

        new_title, ok = QInputDialog.getText(
            self.history_list, "Rename Recording", "New Title:", text=current_text
        )

        if ok and new_title:
            try:
                self.db.update_recording_title(rec_id, new_title)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self.history_list, "Error", f"Failed to rename recording: {e}")

    def refresh(self):
        """Refresh the history list from database."""
        self.history_list.clear()
        try:
            recordings = self.db.get_recordings()
            for rec in recordings:
                # Format timestamp
                ts = rec["started_at"]
                try:
                    dt = datetime.fromisoformat(ts)
                    display_ts = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
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
            logger.error("Error refreshing history: %s", e)

    def _load_item(self, item: QListWidgetItem):
        """Load a history item's details."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self.selected_rec_id = rec_id

        transcript = self.db.get_transcript(rec_id)
        action_items = self.db.get_action_items(rec_id)

        if transcript:
            text = transcript["text"]
            if transcript["summary"]:
                text = f"## Summary\n{transcript['summary']}\n\n## Transcript\n{text}"
            self.transcript_edit.setText(text)
            self.transcribe_btn.setText("Re-transcribe")
        else:
            self.transcript_edit.setText("No transcript available for this recording.")
            self.transcribe_btn.setText("Transcribe")

        self.actions_list.clear()
        if action_items:
            for action in action_items:
                label = f"{action['text']}"
                if action["assignee"]:
                    label += f" ({action['assignee']})"
                self.actions_list.addItem(label)
        else:
            self.actions_list.addItem("No action items found.")

        self.transcribe_btn.setEnabled(True)

    def _transcribe_selected(self):
        """Transcribe the selected history item."""
        if not self.selected_rec_id:
            return

        if not config.get("api_key"):
            QMessageBox.warning(
                self.transcribe_btn,
                "Missing API Key",
                "Please set your Gemini API Key in Settings.",
            )
            return

        # Get recording details to find path
        rec = self.db.get_recording(self.selected_rec_id)
        if not rec:
            QMessageBox.warning(self.transcribe_btn, "Error", "Recording not found in database.")
            return

        # Derive session directory from mic_path
        mic_path = rec["mic_path"]
        session_dir = os.path.dirname(mic_path)

        if not os.path.exists(session_dir):
            QMessageBox.warning(
                self.transcribe_btn,
                "Error",
                f"Recording directory not found: {session_dir}",
            )
            return

        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.setText("Transcribing...")
        self.transcript_edit.setText("Processing audio and sending to Gemini...")

        self._worker = TranscribeWorker(session_dir)
        self._worker.finished.connect(self._on_transcription_finished)
        self._worker.error.connect(self._on_transcription_error)
        self._worker.start()

    def _on_transcription_finished(self, json_str: str):
        """Handle successful transcription."""
        self.transcribe_btn.setText("Re-transcribe")
        self.transcribe_btn.setEnabled(True)

        result = parse_transcription_result(json_str)

        # Display transcript
        display_text = format_transcript_display(result["transcript"], result["summary"])
        self.transcript_edit.setText(display_text)

        # Display action items
        self.actions_list.clear()
        for action in result["action_items"]:
            self.actions_list.addItem(format_action_item(action))

        # Save to DB
        if self.selected_rec_id:
            self.db.save_transcript(self.selected_rec_id, result["transcript"], result["summary"])
            if not result["parse_error"]:
                self.db.save_action_items(self.selected_rec_id, result["action_items"])

    def _on_transcription_error(self, error_msg: str):
        """Handle transcription error."""
        self.transcribe_btn.setText("Transcribe")
        self.transcribe_btn.setEnabled(True)
        self.transcript_edit.setText(f"Error: {error_msg}")
        QMessageBox.warning(self.transcribe_btn, "Transcription Error", error_msg)
