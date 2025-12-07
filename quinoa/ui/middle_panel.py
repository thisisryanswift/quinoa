"""Middle panel - Notes editor, transcript viewer, and recording controls."""

import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import quinoa_audio
from quinoa.config import config
from quinoa.constants import (
    DEFAULT_SAMPLE_RATE,
    LAYOUT_MARGIN,
    LAYOUT_MARGIN_SMALL,
    LAYOUT_SPACING,
    MIN_DISK_SPACE_BYTES,
    NOTES_AUTO_SAVE_INTERVAL_MS,
    TIMER_INTERVAL_MS,
    PanelMode,
    ViewType,
)
from quinoa.storage.database import Database
from quinoa.ui.enhance_worker import EnhanceWorker
from quinoa.ui.rich_text_editor import RichTextEditor
from quinoa.ui.styles import (
    BUTTON_PAUSE,
    BUTTON_RECORD,
    BUTTON_STOP,
    LEVEL_METER_MIC,
    LEVEL_METER_SYSTEM,
    MEETING_HEADER_CHIP,
    SPEAKER_COLORS,
    STATUS_LABEL,
    STATUS_LABEL_PAUSED,
    VIEW_SELECTOR_STYLE,
)
from quinoa.ui.transcribe_worker import TranscribeWorker
from quinoa.ui.transcript_handler import (
    format_transcript_display,
    parse_transcription_result,
    utterances_from_json,
    utterances_to_json,
)
from quinoa.ui.transcript_view import TranscriptView

logger = logging.getLogger("quinoa")


class MiddlePanel(QWidget):
    """Middle panel with notes/transcript view and recording controls."""

    # Signals
    recording_started = pyqtSignal(str)  # recording_id
    recording_stopped = pyqtSignal(str)  # recording_id
    recording_state_changed = pyqtSignal(bool)  # is_recording
    transcription_completed = pyqtSignal(str)  # recording_id

    def __init__(
        self,
        db: Database,
        parent: QWidget | None = None,
        on_history_changed: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.db = db
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
        self.device_monitor = None
        self._mode = PanelMode.IDLE

        # Viewing state
        self._viewing_rec_id: str | None = None
        self._current_view = ViewType.TRANSCRIPT
        self._cached_notes = ""
        self._cached_transcript = ""
        self._cached_enhanced = ""
        self._cached_utterances: list[dict] = []
        self._cached_speaker_names: dict[str, str] = {}

        # Timers
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_timer)

        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self._auto_save_notes)

        # Transcription worker
        self._worker: TranscribeWorker | None = None
        self._transcribing_rec_id: str | None = None

        # Enhancement worker
        self._enhance_worker: EnhanceWorker | None = None

        self._setup_ui()
        self.refresh_devices()
        self._start_device_monitor()

    def _setup_ui(self):
        """Setup the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(LAYOUT_MARGIN, LAYOUT_MARGIN, LAYOUT_MARGIN, LAYOUT_MARGIN)
        layout.setSpacing(LAYOUT_SPACING)

        # Meeting header (visible when viewing a meeting)
        self.meeting_header = self._create_meeting_header()
        self.meeting_header.setVisible(False)
        layout.addWidget(self.meeting_header)

        # Content area (stacked widget for notes/transcript)
        self.content_stack = QStackedWidget()

        # Page 0: Notes editor (for recording or idle)
        self.notes_editor = self._create_notes_editor()
        self.content_stack.addWidget(self.notes_editor)

        # Page 1: Plain text transcript viewer (fallback)
        self.transcript_viewer = RichTextEditor()
        self.transcript_viewer.set_read_only(True)
        self.transcript_viewer.set_placeholder_text("Select a meeting to view its transcript...")
        self.content_stack.addWidget(self.transcript_viewer)

        # Page 2: Chat-bubble transcript viewer (for diarized transcripts)
        self.diarized_transcript_view = TranscriptView()
        self.diarized_transcript_view.utterances_changed.connect(self._on_utterances_changed)
        self.diarized_transcript_view.speaker_names_changed.connect(self._on_speaker_names_changed)
        self.diarized_transcript_view.set_as_me_requested.connect(self._set_speaker_as_me)
        self.diarized_transcript_view.merge_speakers_requested.connect(self._merge_speakers)
        self.content_stack.addWidget(self.diarized_transcript_view)

        layout.addWidget(self.content_stack, stretch=1)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        controls_widget = self._create_recording_controls()
        layout.addWidget(controls_widget)

    def _create_meeting_header(self) -> QWidget:
        """Create the meeting header with title and metadata chips."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(8)

        # Title (clickable to rename)
        self.header_title = QPushButton()
        self.header_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_title.setStyleSheet("""
            QPushButton {
                font-size: 20px;
                font-weight: bold;
                color: #ffffff;
                background: transparent;
                border: none;
                text-align: left;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                color: #4a9eff;
            }
        """)
        self.header_title.clicked.connect(self._rename_meeting_from_header)
        layout.addWidget(self.header_title)

        # Metadata chips row
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        self.header_date_chip = QLabel()
        self.header_date_chip.setStyleSheet(MEETING_HEADER_CHIP)
        chips_row.addWidget(self.header_date_chip)

        self.header_duration_chip = QLabel()
        self.header_duration_chip.setStyleSheet(MEETING_HEADER_CHIP)
        chips_row.addWidget(self.header_duration_chip)

        chips_row.addStretch()
        layout.addLayout(chips_row)

        # Speakers row
        self.speakers_row = QHBoxLayout()
        self.speakers_row.setSpacing(6)
        self.speakers_label = QLabel("Speakers:")
        self.speakers_label.setStyleSheet("color: #888; font-size: 12px;")
        self.speakers_row.addWidget(self.speakers_label)
        self.speaker_chips_container = QWidget()
        self.speaker_chips_layout = QHBoxLayout(self.speaker_chips_container)
        self.speaker_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.speaker_chips_layout.setSpacing(6)
        self.speakers_row.addWidget(self.speaker_chips_container)
        self.speakers_row.addStretch()
        layout.addLayout(self.speakers_row)

        # Initially hidden until we have speakers
        self.speakers_label.setVisible(False)
        self.speaker_chips_container.setVisible(False)

        return widget

    def _update_meeting_header(self, rec_id: str) -> None:
        """Update the meeting header with recording info."""
        rec = self.db.get_recording(rec_id)
        if not rec:
            return

        # Title
        self.header_title.setText(rec["title"])

        # Date chip
        try:
            dt = datetime.fromisoformat(rec["started_at"])
            date_str = dt.strftime("%b %d, %Y • %I:%M %p")
        except (ValueError, TypeError):
            date_str = str(rec["started_at"])
        self.header_date_chip.setText(f"📅 {date_str}")

        # Duration chip
        duration = rec.get("duration_seconds", 0)
        if duration:
            mins = int(duration // 60)
            secs = int(duration % 60)
            self.header_duration_chip.setText(f"⏱ {mins}:{secs:02d}")
            self.header_duration_chip.setVisible(True)
        else:
            self.header_duration_chip.setVisible(False)

    def _update_speaker_chips(self) -> None:
        """Update speaker chips in the header based on cached utterances."""
        # Clear existing chips
        while self.speaker_chips_layout.count():
            item = self.speaker_chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._cached_utterances:
            self.speakers_label.setVisible(False)
            self.speaker_chips_container.setVisible(False)
            return

        # Get unique speakers in order of appearance
        speakers_seen = []
        for u in self._cached_utterances:
            speaker = u.get("speaker", "Unknown")
            if speaker not in speakers_seen:
                speakers_seen.append(speaker)

        # Assign colors
        speaker_colors = {}
        for i, speaker in enumerate(speakers_seen):
            if speaker.lower() == "me":
                speaker_colors[speaker] = SPEAKER_COLORS[0]
            else:
                color_idx = (i + 1) % len(SPEAKER_COLORS)
                speaker_colors[speaker] = SPEAKER_COLORS[color_idx]

        # Create chips
        for speaker in speakers_seen:
            display_name = self._cached_speaker_names.get(speaker, speaker)
            color = speaker_colors.get(speaker, SPEAKER_COLORS[1])

            chip = QPushButton(display_name)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color}22;
                    color: {color};
                    border: 1px solid {color};
                    border-radius: 12px;
                    padding: 4px 12px;
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {color}44;
                }}
            """)
            chip.clicked.connect(
                lambda checked, s=speaker, c=chip: self._on_speaker_chip_clicked(s, c)
            )
            self.speaker_chips_layout.addWidget(chip)

        self.speakers_label.setVisible(True)
        self.speaker_chips_container.setVisible(True)

    def _on_speaker_chip_clicked(self, speaker: str, chip: QPushButton) -> None:
        """Show context menu when clicking a speaker chip."""
        display_name = self._cached_speaker_names.get(speaker, speaker)

        menu = QMenu(self)

        # Rename option
        rename_action = QAction(f'Rename "{display_name}"...', self)
        rename_action.triggered.connect(lambda: self._rename_speaker(speaker))
        menu.addAction(rename_action)

        # Set as Me option (only if not already "Me")
        if speaker.lower() != "me":
            set_as_me_action = QAction("Set as Me", self)
            set_as_me_action.triggered.connect(lambda: self._set_speaker_as_me(speaker))
            menu.addAction(set_as_me_action)

        # Merge with submenu
        other_speakers = self._get_other_speakers(speaker)
        if other_speakers:
            menu.addSeparator()
            merge_menu = menu.addMenu("Merge with")
            for other in other_speakers:
                other_display = self._cached_speaker_names.get(other, other)
                merge_action = QAction(other_display, self)
                merge_action.triggered.connect(
                    lambda checked, target=other: self._merge_speakers(speaker, target)
                )
                merge_menu.addAction(merge_action)

        # Reset to original option (only if any utterances have been modified)
        if self._speaker_has_modifications(speaker):
            menu.addSeparator()
            reset_action = QAction("Reset to original", self)
            reset_action.triggered.connect(lambda: self._reset_speaker_to_original(speaker))
            menu.addAction(reset_action)

        # Show menu below the chip
        menu.exec(chip.mapToGlobal(chip.rect().bottomLeft()))

    def _rename_speaker(self, speaker: str) -> None:
        """Rename a speaker globally."""
        current_name = self._cached_speaker_names.get(speaker, speaker)

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Speaker",
            f'Rename "{current_name}" to:',
            text=current_name,
        )

        if ok and new_name and new_name != current_name:
            self._cached_speaker_names[speaker] = new_name
            self._save_speaker_changes_and_refresh()

    def _get_other_speakers(self, exclude_speaker: str) -> list[str]:
        """Get list of speakers excluding the given one."""
        speakers = []
        for u in self._cached_utterances:
            s = u.get("speaker", "Unknown")
            if s != exclude_speaker and s not in speakers:
                speakers.append(s)
        return speakers

    def _speaker_has_modifications(self, speaker: str) -> bool:
        """Check if any utterances for this speaker have been modified from original."""
        for u in self._cached_utterances:
            if u.get("speaker") == speaker:
                original = u.get("original_speaker")
                if original and original != speaker:
                    return True
        return False

    def _get_next_speaker_name(self) -> str:
        """Get next available 'Speaker N' name."""
        existing_speakers = set()
        for u in self._cached_utterances:
            existing_speakers.add(u.get("speaker", ""))

        n = 2
        while f"Speaker {n}" in existing_speakers:
            n += 1
        return f"Speaker {n}"

    def _set_speaker_as_me(self, speaker: str) -> None:
        """Designate a speaker as 'Me', renaming current 'Me' to generic name."""
        if speaker.lower() == "me":
            return  # Already "Me"

        # Find a name for the old "Me"
        new_name_for_old_me = self._get_next_speaker_name()

        # Update all utterances
        for u in self._cached_utterances:
            current = u.get("speaker", "")
            if current.lower() == "me":
                u["speaker"] = new_name_for_old_me
            elif current == speaker:
                u["speaker"] = "Me"

        # Clear display name mappings for affected speakers
        self._cached_speaker_names.pop(speaker, None)
        self._cached_speaker_names.pop("Me", None)

        self._save_utterances_and_refresh()

    def _merge_speakers(self, source_speaker: str, target_speaker: str) -> None:
        """Merge source speaker into target speaker."""
        # Update all utterances from source to target
        for u in self._cached_utterances:
            if u.get("speaker") == source_speaker:
                u["speaker"] = target_speaker

        # Remove display name mapping for source (it no longer exists)
        self._cached_speaker_names.pop(source_speaker, None)

        self._save_utterances_and_refresh()

    def _reset_speaker_to_original(self, speaker: str) -> None:
        """Reset a speaker's utterances to their original Gemini labels."""
        for u in self._cached_utterances:
            if u.get("speaker") == speaker:
                original = u.get("original_speaker")
                if original:
                    u["speaker"] = original

        # Clear display name mapping
        self._cached_speaker_names.pop(speaker, None)

        self._save_utterances_and_refresh()

    def _save_utterances_and_refresh(self) -> None:
        """Save utterances to database and refresh UI."""
        if self._viewing_rec_id:
            self.db.update_utterances(
                self._viewing_rec_id, utterances_to_json(self._cached_utterances)
            )
            self.db.save_speaker_names(self._viewing_rec_id, json.dumps(self._cached_speaker_names))

        # Refresh transcript view
        if self._current_view == ViewType.TRANSCRIPT and self._cached_utterances:
            self.diarized_transcript_view.set_utterances(
                self._cached_utterances, self._cached_speaker_names
            )

        # Refresh speaker chips
        self._update_speaker_chips()

    def _save_speaker_changes_and_refresh(self) -> None:
        """Save speaker name mappings and refresh UI."""
        if self._viewing_rec_id:
            self.db.save_speaker_names(self._viewing_rec_id, json.dumps(self._cached_speaker_names))

        # Refresh transcript view
        if self._current_view == ViewType.TRANSCRIPT and self._cached_utterances:
            self.diarized_transcript_view.set_utterances(
                self._cached_utterances, self._cached_speaker_names
            )

        # Refresh speaker chips
        self._update_speaker_chips()

    def _create_notes_editor(self) -> RichTextEditor:
        """Create the WYSIWYG notes editor."""
        editor = RichTextEditor()
        editor.set_placeholder_text("Take notes during your meeting...")
        return editor

    def _create_view_selector(self) -> QWidget:
        """Create the view selector for historic meetings."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create button group for mutual exclusivity
        self.view_button_group = QButtonGroup(self)

        # Notes button
        self.notes_btn = QPushButton("Notes")
        self.notes_btn.setCheckable(True)
        self.notes_btn.setStyleSheet(VIEW_SELECTOR_STYLE)
        self.view_button_group.addButton(self.notes_btn, ViewType.NOTES)
        layout.addWidget(self.notes_btn)

        # Transcript button
        self.transcript_btn = QPushButton("Transcript")
        self.transcript_btn.setCheckable(True)
        self.transcript_btn.setChecked(True)  # Default view
        self.transcript_btn.setStyleSheet(VIEW_SELECTOR_STYLE)
        self.view_button_group.addButton(self.transcript_btn, ViewType.TRANSCRIPT)
        layout.addWidget(self.transcript_btn)

        # Enhanced button
        self.enhanced_btn = QPushButton("Enhanced")
        self.enhanced_btn.setCheckable(True)
        self.enhanced_btn.setStyleSheet(VIEW_SELECTOR_STYLE)
        self.view_button_group.addButton(self.enhanced_btn, ViewType.ENHANCED)
        layout.addWidget(self.enhanced_btn)

        layout.addStretch()

        # Enhance button (visible only in Enhanced view when enhancement is needed)
        self.enhance_notes_btn = QPushButton("Generate Enhanced Notes")
        self.enhance_notes_btn.setVisible(False)
        self.enhance_notes_btn.clicked.connect(self._start_enhancement)
        layout.addWidget(self.enhance_notes_btn)

        # Connect button group signal
        self.view_button_group.idClicked.connect(self._on_view_changed)

        return widget

    def _on_view_changed(self, view_id: int) -> None:
        """Handle view selector button click."""
        new_view = ViewType(view_id)
        if self._current_view == ViewType.NOTES and new_view != ViewType.NOTES:
            self._save_current_notes()

        self._current_view = new_view
        self._update_view_content()

    def _update_view_content(self) -> None:
        """Update the displayed content based on current view."""
        # Hide enhance button by default
        self.enhance_notes_btn.setVisible(False)

        if self._current_view == ViewType.NOTES:
            # Show notes in editable notes_editor
            self.notes_editor.set_markdown(self._cached_notes)
            self.content_stack.setCurrentIndex(0)
        elif self._current_view == ViewType.TRANSCRIPT:
            # Show transcript - use diarized view if utterances available
            if self._cached_utterances:
                self.diarized_transcript_view.set_utterances(
                    self._cached_utterances, self._cached_speaker_names
                )
                self.content_stack.setCurrentIndex(2)  # Diarized view
            else:
                self.transcript_viewer.set_markdown(self._cached_transcript)
                self.content_stack.setCurrentIndex(1)  # Plain text fallback
        elif self._current_view == ViewType.ENHANCED:
            # Show enhanced notes or prompt to generate
            if self._cached_enhanced:
                self.transcript_viewer.set_markdown(self._cached_enhanced)
            else:
                # Show placeholder and enable generate button if we have notes + transcript
                can_enhance = bool(self._cached_notes and self._cached_transcript)
                if can_enhance:
                    self.transcript_viewer.set_markdown(
                        "## Enhanced Notes\n\n"
                        "Click **Generate Enhanced Notes** to create AI-enhanced notes "
                        "that expand your notes with context from the transcript."
                    )
                    self.enhance_notes_btn.setVisible(True)
                else:
                    missing = []
                    if not self._cached_notes:
                        missing.append("notes")
                    if not self._cached_transcript:
                        missing.append("transcript")
                    self.transcript_viewer.set_markdown(
                        "## Enhanced Notes\n\n"
                        f"Cannot generate enhanced notes. Missing: {', '.join(missing)}.\n\n"
                        "Enhanced notes require both user notes and a transcript."
                    )
            self.content_stack.setCurrentIndex(1)

    def _create_recording_controls(self) -> QWidget:
        """Create the recording controls widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT_MARGIN_SMALL)

        # View selector (only visible in viewing mode)
        self.view_selector_widget = self._create_view_selector()
        self.view_selector_widget.setVisible(False)
        layout.addWidget(self.view_selector_widget)

        # Recording controls container (hidden when viewing history)
        self.recording_controls_container = QWidget()
        rec_layout = QVBoxLayout(self.recording_controls_container)
        rec_layout.setContentsMargins(0, 0, 0, 0)
        rec_layout.setSpacing(LAYOUT_MARGIN_SMALL)

        # Device selection row
        dev_row = QHBoxLayout()

        dev_row.addWidget(QLabel("Mic:"))
        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(150)
        dev_row.addWidget(self.mic_combo, stretch=1)

        self.sys_audio_check = QCheckBox("System Audio")
        self.sys_audio_check.setChecked(True)
        dev_row.addWidget(self.sys_audio_check)

        rec_layout.addLayout(dev_row)

        # Level meters row
        meters_row = QHBoxLayout()

        meters_row.addWidget(QLabel("Mic:"))
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setStyleSheet(LEVEL_METER_MIC)
        self.mic_level_bar.setMaximumHeight(15)
        meters_row.addWidget(self.mic_level_bar, stretch=1)

        meters_row.addWidget(QLabel("Sys:"))
        self.sys_level_bar = QProgressBar()
        self.sys_level_bar.setRange(0, 100)
        self.sys_level_bar.setTextVisible(False)
        self.sys_level_bar.setStyleSheet(LEVEL_METER_SYSTEM)
        self.sys_level_bar.setMaximumHeight(15)
        meters_row.addWidget(self.sys_level_bar, stretch=1)

        rec_layout.addLayout(meters_row)

        # Status label (inside recording container)
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(STATUS_LABEL)
        rec_layout.addWidget(self.status_label)

        # Recording buttons row
        rec_btn_row = QHBoxLayout()

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(40)
        self.record_btn.setStyleSheet(BUTTON_RECORD)
        self.record_btn.clicked.connect(self.toggle_recording)
        rec_btn_row.addWidget(self.record_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumHeight(40)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet(BUTTON_PAUSE)
        self.pause_btn.clicked.connect(self.toggle_pause)
        rec_btn_row.addWidget(self.pause_btn)

        rec_layout.addLayout(rec_btn_row)

        layout.addWidget(self.recording_controls_container)

        # Transcribe button (always visible, outside container)
        self.transcribe_btn = QPushButton("Transcribe")
        self.transcribe_btn.setMinimumHeight(40)
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self._start_transcription)
        layout.addWidget(self.transcribe_btn)

        return widget

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
            logger.error("Failed to list devices: %s", e)
            self.record_btn.setEnabled(False)

    def load_meeting(self, rec_id: str):
        """Load a meeting for viewing."""
        if self.recording_session:
            # Don't switch while recording
            return

        # Save any pending notes from previous view
        if self._mode == PanelMode.VIEWING and self._current_view == ViewType.NOTES:
            self._save_current_notes()

        self._viewing_rec_id = rec_id
        self._mode = PanelMode.VIEWING

        # Load and cache all data
        transcript_data = self.db.get_transcript(rec_id)
        self._cached_notes = self.db.get_notes(rec_id)
        self._cached_enhanced = self.db.get_enhanced_notes(rec_id)

        # Load utterances and speaker names
        if transcript_data:
            self._cached_utterances = utterances_from_json(transcript_data.get("utterances"))
            speaker_names_json = transcript_data.get("speaker_names")
            if speaker_names_json:
                try:
                    self._cached_speaker_names = json.loads(speaker_names_json)
                except json.JSONDecodeError:
                    self._cached_speaker_names = {}
            else:
                self._cached_speaker_names = {}
        else:
            self._cached_utterances = []
            self._cached_speaker_names = {}

        # Build transcript display text
        if transcript_data:
            text = transcript_data["text"]
            if transcript_data["summary"]:
                text = f"## Summary\n{transcript_data['summary']}\n\n## Transcript\n{text}"
            self._cached_transcript = text
            self.transcribe_btn.setText("Re-transcribe")
        else:
            self._cached_transcript = "No transcript available. Click Transcribe to generate one."
            self.transcribe_btn.setText("Transcribe")

        # Show meeting header
        self._update_meeting_header(rec_id)
        self._update_speaker_chips()
        self.meeting_header.setVisible(True)

        # Hide recording controls, show view selector
        self.recording_controls_container.setVisible(False)
        self.view_selector_widget.setVisible(True)
        self._current_view = ViewType.TRANSCRIPT
        self.transcript_btn.setChecked(True)

        # Update button states
        self.enhanced_btn.setEnabled(bool(self._cached_notes and transcript_data))

        self.transcribe_btn.setEnabled(True)
        self._update_view_content()

    def clear_view(self):
        """Clear the view and return to idle mode."""
        if self.recording_session:
            return

        # Save notes if we were editing them
        if self._mode == PanelMode.VIEWING and self._current_view == ViewType.NOTES:
            self._save_current_notes()

        self._viewing_rec_id = None
        self._mode = PanelMode.IDLE

        # Clear cached data
        self._cached_notes = ""
        self._cached_transcript = ""
        self._cached_enhanced = ""
        self._cached_utterances = []
        self._cached_speaker_names = {}
        self.diarized_transcript_view.clear()

        # Hide view selector and meeting header, show recording controls
        self.view_selector_widget.setVisible(False)
        self.meeting_header.setVisible(False)
        self.recording_controls_container.setVisible(True)

        self._set_notes_text("")
        self.transcript_viewer.clear()
        self.transcribe_btn.setEnabled(False)
        self.content_stack.setCurrentIndex(0)  # Show notes editor

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
            QMessageBox.critical(self, "Error", f"Failed to toggle pause: {str(e)}")

    def _check_disk_space(self) -> bool:
        """Check if there's enough disk space for recording."""
        output_dir = config.get("output_dir")
        if not output_dir:
            return False

        try:
            if not os.path.exists(output_dir):
                return True
            total, used, free = shutil.disk_usage(output_dir)
            if free < MIN_DISK_SPACE_BYTES:
                QMessageBox.warning(
                    self,
                    "Low Disk Space",
                    f"Only {free // (1024 * 1024)} MB free in {output_dir}.",
                )
                return False
        except Exception as e:
            logger.warning("Failed to check disk space: %s", e)
        return True

    def _start_recording(self):
        """Start a new recording session."""
        mic_id = self.mic_combo.currentData()
        if not mic_id:
            QMessageBox.warning(self, "Warning", "Please select a microphone.")
            return

        # Check for Bluetooth A2DP
        for device in self.devices:
            if device.id == mic_id and device.is_bluetooth:
                profile = getattr(device, "bluetooth_profile", None)
                if profile and "a2dp" in profile.lower():
                    reply = QMessageBox.warning(
                        self,
                        "Bluetooth Warning",
                        f"'{device.name}' is in A2DP mode. Mic may not work.\nContinue?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.No:
                        return

        if not self._check_disk_space():
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_rec_id = f"rec_{timestamp}"

            base_dir = config.get("output_dir")
            if not base_dir:
                QMessageBox.critical(self, "Error", "Output directory not set.")
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
            self._mode = PanelMode.RECORDING

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

            # Clear notes for new recording
            self._set_notes_text("")
            self.content_stack.setCurrentIndex(0)  # Show notes editor

            # Update UI
            self.record_btn.setText("Stop Recording")
            self.record_btn.setStyleSheet(BUTTON_STOP)
            self.mic_combo.setEnabled(False)
            self.sys_audio_check.setEnabled(False)
            self.transcribe_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.status_label.setText("Recording...")

            # Start timers
            self.timer.start(TIMER_INTERVAL_MS)
            self.auto_save_timer.start(NOTES_AUTO_SAVE_INTERVAL_MS)

            # Emit signals
            self.recording_started.emit(self.current_rec_id)
            self.recording_state_changed.emit(True)
            if self.on_history_changed:
                self.on_history_changed()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start recording: {str(e)}")

    def _stop_recording(self):
        """Stop the current recording session."""
        if not self.recording_session:
            return

        try:
            self.recording_session.stop()
        except Exception as e:
            logger.error("Error stopping session: %s", e)

        # Save notes before stopping
        self._save_notes()

        # Update DB
        duration = time.time() - self.recording_start_time - self.recording_paused_time
        self.db.update_recording_status(
            self.current_rec_id,
            "completed",
            duration=duration,
            ended_at=datetime.now(),
        )

        rec_id = self.current_rec_id
        self.recording_session = None
        self._mode = PanelMode.IDLE

        # Stop timers
        self.timer.stop()
        self.auto_save_timer.stop()

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
        self.status_label.setText("Recording saved")

        # Emit signals
        self.recording_stopped.emit(rec_id)
        self.recording_state_changed.emit(False)
        if self.on_history_changed:
            self.on_history_changed()

    def _auto_save_notes(self):
        """Auto-save notes during recording."""
        if self.recording_session and self.current_rec_id:
            self._save_notes()

    def _save_notes(self):
        """Save current notes to database."""
        rec_id = self.current_rec_id if self._mode == PanelMode.RECORDING else self._viewing_rec_id
        if rec_id:
            notes = self._get_notes_text()
            if notes:
                self.db.save_notes(rec_id, notes)
                logger.debug("Notes auto-saved for %s", rec_id)

    def _save_current_notes(self):
        """Save notes from the editor when in viewing mode."""
        if self._viewing_rec_id and self._current_view == ViewType.NOTES:
            notes = self.notes_editor.get_markdown()
            self._cached_notes = notes  # Update cache
            if notes:
                self.db.save_notes(self._viewing_rec_id, notes)
                logger.debug("Notes saved for %s", self._viewing_rec_id)

    def _on_utterances_changed(self, utterances: list[dict]):
        """Handle utterances being edited (speaker reassignment)."""
        if self._viewing_rec_id:
            self._cached_utterances = utterances
            self.db.update_utterances(self._viewing_rec_id, utterances_to_json(utterances))
            self._update_speaker_chips()  # Refresh header chips (speaker list may have changed)
            logger.debug("Utterances updated for %s", self._viewing_rec_id)

    def _on_speaker_names_changed(self, speaker_names: dict[str, str]):
        """Handle speaker names being edited."""
        if self._viewing_rec_id:
            self._cached_speaker_names = speaker_names
            self.db.save_speaker_names(self._viewing_rec_id, json.dumps(speaker_names))
            self._update_speaker_chips()  # Refresh header chips
            logger.debug("Speaker names updated for %s", self._viewing_rec_id)

    def _rename_meeting_from_header(self):
        """Rename meeting when clicking the header title."""
        if not self._viewing_rec_id:
            return

        current_title = self.header_title.text()
        new_title, ok = QInputDialog.getText(self, "Rename Meeting", "Title:", text=current_title)

        if ok and new_title and new_title != current_title:
            self.db.update_recording_title(self._viewing_rec_id, new_title)
            self.header_title.setText(new_title)
            # Notify left panel to refresh
            if self.on_history_changed:
                self.on_history_changed()

    def on_meeting_renamed(self, rec_id: str, new_title: str):
        """Handle meeting rename from left panel."""
        if self._viewing_rec_id == rec_id:
            self.header_title.setText(new_title)

    def _get_notes_text(self) -> str:
        """Get markdown text from notes editor."""
        return self.notes_editor.get_markdown()

    def _set_notes_text(self, text: str) -> None:
        """Set markdown text in notes editor."""
        self.notes_editor.set_markdown(text)

    def _update_timer(self):
        """Update timer display and poll events."""
        if self.recording_session:
            self._update_elapsed_time()
            self._poll_recording_events()
        self._poll_device_events()

    def _update_elapsed_time(self):
        """Update the elapsed time display."""
        if self.is_paused:
            current_pause = time.time() - self.pause_start_time
            elapsed = (
                time.time() - self.recording_start_time - self.recording_paused_time - current_pause
            )
        else:
            elapsed = time.time() - self.recording_start_time - self.recording_paused_time

        mins = int(elapsed // 60)
        secs = int(elapsed % 60)

        if self.is_paused:
            self.status_label.setText(f"Paused: {mins:02d}:{secs:02d}")
        else:
            self.status_label.setText(f"Recording: {mins:02d}:{secs:02d}")

    def _poll_recording_events(self):
        """Poll and handle recording events."""
        try:
            events = self.recording_session.poll_events()
            for event in events:
                if event.type_ == "levels":
                    if event.mic_level is not None:
                        self.mic_level_bar.setValue(min(100, int(event.mic_level * 100)))
                    if event.system_level is not None:
                        self.sys_level_bar.setValue(min(100, int(event.system_level * 100)))
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
                    self.status_label.setText("Reconnecting...")
                    self.status_label.setStyleSheet(STATUS_LABEL_PAUSED)
                elif event.type_ == "started":
                    self.status_label.setText("Recording...")
                    self.status_label.setStyleSheet(STATUS_LABEL)
        except Exception as e:
            logger.error("Error polling events: %s", e)

    def _poll_device_events(self):
        """Poll device monitor for hot-plug events."""
        if self.device_monitor:
            try:
                device_events = self.device_monitor.poll()
                for event in device_events:
                    # Only react to real device changes (ignore spurious events with no name)
                    if event.type_ in ["added", "removed"] and event.device_name:
                        logger.info("Device %s: %s", event.type_, event.device_name)
                        self.refresh_devices()
                        break
            except Exception as e:
                logger.error("Error polling device events: %s", e)

    def _handle_audio_error(self, error_msg: str):
        """Handle audio errors."""
        friendly_msg = error_msg
        if "PipeWire" in error_msg:
            if "connection" in error_msg.lower():
                friendly_msg = "Lost connection to audio server. Check settings or restart."
            else:
                friendly_msg = f"Audio server error: {error_msg}"
        elif "device" in error_msg.lower() and "not found" in error_msg.lower():
            friendly_msg = "Microphone not found. It may have been unplugged."

        logger.error("Audio Error: %s", error_msg)
        self.status_label.setText("Error occurred")
        QMessageBox.critical(self, "Audio Error", friendly_msg)

    def _start_transcription(self):
        """Start transcription."""
        if not config.get("api_key"):
            QMessageBox.warning(self, "Missing API Key", "Set your Gemini API Key in Settings.")
            return

        # Determine which recording to transcribe
        if self._mode == PanelMode.VIEWING and self._viewing_rec_id:
            rec = self.db.get_recording(self._viewing_rec_id)
            if not rec:
                QMessageBox.warning(self, "Error", "Recording not found.")
                return
            session_dir = os.path.dirname(rec["mic_path"])
            rec_id = self._viewing_rec_id
        elif self.current_session_dir:
            session_dir = self.current_session_dir
            rec_id = self.current_rec_id
        else:
            return

        if not os.path.exists(session_dir):
            QMessageBox.warning(self, "Error", f"Directory not found: {session_dir}")
            return

        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.setText("Transcribing...")
        self.status_label.setText("Transcribing...")

        self._transcribing_rec_id = rec_id
        self._worker = TranscribeWorker(session_dir)
        self._worker.finished.connect(self._on_transcription_finished)
        self._worker.error.connect(self._on_transcription_error)
        self._worker.start()

    def _on_transcription_finished(self, json_str: str):
        """Handle transcription completion."""
        self.status_label.setText("Transcription Complete")
        self.transcribe_btn.setEnabled(True)
        self.transcribe_btn.setText("Re-transcribe")

        result = parse_transcription_result(json_str)
        utterances = result.get("utterances", [])
        display_text = format_transcript_display(result["transcript"], result["summary"])

        # Update cached data
        self._cached_utterances = utterances
        self._cached_transcript = display_text
        self._cached_speaker_names = {}  # Reset speaker names on new transcription

        # Update speaker chips in header
        self._update_speaker_chips()

        # Display using diarized view if utterances available (regardless of mode)
        if utterances:
            self.diarized_transcript_view.set_utterances(utterances, {})
            self.content_stack.setCurrentIndex(2)  # Diarized view
        else:
            # Fallback to plain text viewer
            if self._mode == PanelMode.VIEWING and self._transcribing_rec_id:
                notes = self.db.get_notes(self._transcribing_rec_id)
                if notes:
                    display_text = f"## Notes\n{notes}\n\n{display_text}"
            self.transcript_viewer.set_markdown(display_text)
            self.content_stack.setCurrentIndex(1)

        # Save to DB
        if self._transcribing_rec_id:
            utterances_json = utterances_to_json(utterances) if utterances else None
            self.db.save_transcript(
                self._transcribing_rec_id, result["transcript"], result["summary"], utterances_json
            )
            if not result["parse_error"]:
                self.db.save_action_items(self._transcribing_rec_id, result["action_items"])
            self.transcription_completed.emit(self._transcribing_rec_id)
            if self.on_history_changed:
                self.on_history_changed()

    def _on_transcription_error(self, error_msg: str):
        """Handle transcription error."""
        self.status_label.setText("Transcription Failed")
        self.transcribe_btn.setEnabled(True)
        self.transcribe_btn.setText("Transcribe")
        QMessageBox.warning(self, "Transcription Error", error_msg)

    def _start_enhancement(self):
        """Start AI enhancement of notes."""
        if not config.get("api_key"):
            QMessageBox.warning(self, "Missing API Key", "Set your Gemini API Key in Settings.")
            return

        if not self._cached_notes or not self._cached_transcript:
            QMessageBox.warning(
                self, "Cannot Enhance", "Both notes and transcript are required for enhancement."
            )
            return

        # Get summary if available
        summary = None
        if self._viewing_rec_id:
            transcript_data = self.db.get_transcript(self._viewing_rec_id)
            if transcript_data:
                summary = transcript_data.get("summary")

        # Update UI
        self.enhance_notes_btn.setEnabled(False)
        self.enhance_notes_btn.setText("Enhancing...")
        self.status_label.setText("Generating enhanced notes...")

        # Extract just the transcript text (remove summary header if present)
        transcript_text = self._cached_transcript
        if transcript_text.startswith("## Summary"):
            # Find where transcript section starts
            transcript_marker = "## Transcript\n"
            idx = transcript_text.find(transcript_marker)
            if idx != -1:
                transcript_text = transcript_text[idx + len(transcript_marker) :]

        self._enhance_worker = EnhanceWorker(self._cached_notes, transcript_text, summary)
        self._enhance_worker.finished.connect(self._on_enhancement_finished)
        self._enhance_worker.error.connect(self._on_enhancement_error)
        self._enhance_worker.start()

    def _on_enhancement_finished(self, enhanced_notes: str):
        """Handle enhancement completion."""
        self.status_label.setText("Enhancement Complete")
        self.enhance_notes_btn.setEnabled(True)
        self.enhance_notes_btn.setText("Regenerate Enhanced Notes")
        self.enhance_notes_btn.setVisible(False)

        # Update cache and display
        self._cached_enhanced = enhanced_notes
        self.transcript_viewer.set_markdown(enhanced_notes)

        # Save to DB
        if self._viewing_rec_id:
            self.db.save_enhanced_notes(self._viewing_rec_id, enhanced_notes)
            if self.on_history_changed:
                self.on_history_changed()

    def _on_enhancement_error(self, error_msg: str):
        """Handle enhancement error."""
        self.status_label.setText("Enhancement Failed")
        self.enhance_notes_btn.setEnabled(True)
        self.enhance_notes_btn.setText("Generate Enhanced Notes")
        QMessageBox.warning(self, "Enhancement Error", error_msg)

    def focus_notes(self):
        """Focus the notes editor."""
        self.content_stack.setCurrentIndex(0)
        self.notes_editor.setFocus()

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self.recording_session is not None

    @property
    def mode(self) -> int:
        """Get current mode."""
        return self._mode
