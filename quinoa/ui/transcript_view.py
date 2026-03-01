"""Chat-bubble style transcript viewer with speaker editing."""

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from quinoa.ui.styles import SPEAKER_COLORS


def parse_timestamp_to_ms(ts: str | None) -> int | None:
    if not ts:
        return None
    # Remove any brackets or whitespace
    ts = ts.strip("[] \t")
    parts = ts.split(':')
    try:
        if len(parts) == 2:
            m, s = parts
            return (int(m) * 60 + int(float(s))) * 1000
        elif len(parts) == 3:
            h, m, s = parts
            return (int(h) * 3600 + int(m) * 60 + int(float(s))) * 1000
    except ValueError:
        pass
    return None


class SpeakerInputDialog(QDialog):
    def __init__(
        self,
        title: str,
        label_text: str,
        current_name: str,
        suggestions: list[str],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        label = QLabel(label_text)
        layout.addWidget(label)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setCurrentText(current_name)

        for s in suggestions:
            if s and s != current_name:
                self.combo.addItem(s)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_new_name(self) -> str:
        return self.combo.currentText().strip()


class ClickableLabel(QLabel):
    """A label that emits a clicked signal on mouse press."""

    clicked = pyqtSignal(QMouseEvent)

    def mousePressEvent(self, ev: QMouseEvent | None) -> None:
        if ev:
            self.clicked.emit(ev)
        super().mousePressEvent(ev)


class UtteranceBubble(QFrame):
    """A single chat bubble for an utterance."""

    speaker_clicked = pyqtSignal(str, int)  # speaker_name, utterance_index
    timestamp_clicked = pyqtSignal(int)  # ms

    def __init__(
        self,
        speaker: str,
        text: str,
        index: int,
        is_me: bool = False,
        color: str = "#3498db",
        start_time: str | None = None,
        end_time: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.speaker = speaker
        self.index = index
        self.is_me = is_me

        self.start_time_ms = parse_timestamp_to_ms(start_time)
        self.end_time_ms = parse_timestamp_to_ms(end_time)

        self._setup_ui(speaker, text, color, start_time)

    def _setup_ui(self, speaker: str, text: str, color: str, start_time: str | None):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Optional clickable timestamp
        if start_time and self.start_time_ms is not None:
            self.time_label = ClickableLabel(f"▶ {start_time}")
            self.time_label.setStyleSheet(f"""
                QLabel {{
                    color: {color};
                    font-weight: bold;
                    font-size: 11px;
                }}
                QLabel:hover {{
                    text-decoration: underline;
                }}
            """)
            self.time_label.setCursor(Qt.CursorShape.PointingHandCursor)
            ms = self.start_time_ms
            self.time_label.clicked.connect(lambda _e, t=ms: self.timestamp_clicked.emit(t))
            header_layout.addWidget(self.time_label)

        # Speaker label (clickable)
        self.speaker_label = ClickableLabel(f"▼ {speaker}")
        self.speaker_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-weight: bold;
                font-size: 12px;
            }}
            QLabel:hover {{
                text-decoration: underline;
            }}
        """)
        self.speaker_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speaker_label.clicked.connect(
            lambda _e: self.speaker_clicked.emit(self.speaker, self.index)
        )
        header_layout.addWidget(self.speaker_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Text content
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_label.setStyleSheet("""
            QLabel {
                color: #e0e0e0;
                font-size: 14px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(text_label)

        # Bubble styling
        align = "left" if self.is_me else "right"
        border_side = "left" if self.is_me else "right"
        self.setStyleSheet(f"""
            UtteranceBubble {{
                background-color: #2d2d2d;
                border-{border_side}: 3px solid {color};
                border-radius: 8px;
                margin-{align}: 20px;
                margin-top: 4px;
                margin-bottom: 4px;
            }}
        """)

    def update_speaker(self, new_speaker: str, color: str):
        """Update the displayed speaker name."""
        self.speaker = new_speaker
        self.speaker_label.setText(f"▼ {new_speaker}")
        self.speaker_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-weight: bold;
                font-size: 12px;
            }}
            QLabel:hover {{
                text-decoration: underline;
            }}
        """)


class TranscriptView(QScrollArea):
    """Scrollable chat-bubble transcript viewer with speaker editing."""

    # Emitted when utterances or speaker names change
    utterances_changed = pyqtSignal(list)  # Updated utterances
    speaker_names_changed = pyqtSignal(dict)  # Updated speaker_names mapping

    # Emitted for global speaker operations (handled by parent)
    set_as_me_requested = pyqtSignal(str)  # speaker to set as Me
    merge_speakers_requested = pyqtSignal(str, str)  # source, target

    timestamp_clicked = pyqtSignal(int)  # ms

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._utterances: list[dict] = []
        self._speaker_names: dict[str, str] = {}  # original -> display name
        self._speaker_colors: dict[str, str] = {}
        self._speaker_suggestions: list[str] = []
        self._bubbles: list[UtteranceBubble] = []
        self._active_bubble: UtteranceBubble | None = None

        self._setup_ui()

    def set_speaker_suggestions(self, suggestions: list[str]):
        """Set autocomplete suggestions for renaming speakers."""
        self._speaker_suggestions = suggestions

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1e1e1e;
            }
        """)

        # Container widget
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(12, 12, 12, 12)
        self.container_layout.setSpacing(8)
        self.container_layout.addStretch()

        self.setWidget(self.container)

    def set_utterances(
        self,
        utterances: list[dict],
        speaker_names: dict[str, str] | None = None,
    ):
        """Set the utterances to display."""
        self._utterances = utterances
        self._speaker_names = speaker_names or {}
        self._assign_speaker_colors()
        self._rebuild_bubbles()

    def _assign_speaker_colors(self):
        """Assign colors to speakers."""
        self._speaker_colors = {}
        speakers_seen = []

        for u in self._utterances:
            speaker = u.get("speaker", "Unknown")
            if speaker not in speakers_seen:
                speakers_seen.append(speaker)

        for i, speaker in enumerate(speakers_seen):
            if speaker.lower() == "me":
                self._speaker_colors[speaker] = SPEAKER_COLORS[0]
            else:
                color_idx = (i + 1) % len(SPEAKER_COLORS)
                self._speaker_colors[speaker] = SPEAKER_COLORS[color_idx]

    def _get_display_speaker(self, original: str) -> str:
        """Get display name for a speaker."""
        return self._speaker_names.get(original, original)

    def _rebuild_bubbles(self):
        """Rebuild all chat bubbles."""
        self._active_bubble = None
        # Clear existing
        for bubble in self._bubbles:
            bubble.deleteLater()
        self._bubbles = []

        # Remove stretch
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Create bubbles
        for i, u in enumerate(self._utterances):
            original_speaker = u.get("speaker", "Unknown")
            display_speaker = self._get_display_speaker(original_speaker)
            text = u.get("text", "")
            is_me = original_speaker.lower() == "me"
            color = self._speaker_colors.get(original_speaker, SPEAKER_COLORS[1])
            start_time = u.get("start_time")
            end_time = u.get("end_time")

            bubble = UtteranceBubble(
                speaker=display_speaker,
                text=text,
                index=i,
                is_me=is_me,
                color=color,
                start_time=start_time,
                end_time=end_time,
            )
            bubble.speaker_clicked.connect(self._on_speaker_clicked)
            bubble.timestamp_clicked.connect(self.timestamp_clicked.emit)
            self._bubbles.append(bubble)
            self.container_layout.addWidget(bubble)

        # Add stretch at end
        self.container_layout.addStretch()

    def _on_speaker_clicked(self, speaker: str, index: int):
        """Show speaker edit menu."""
        bubble = self._bubbles[index] if index < len(self._bubbles) else None
        if not bubble:
            return

        menu = QMenu(self)
        original_speaker = self._utterances[index].get("speaker", "Unknown")

        # Rename speaker globally
        rename_action = QAction(f'Rename "{speaker}"...', self)
        rename_action.triggered.connect(lambda: self._rename_speaker(speaker))
        menu.addAction(rename_action)

        # Set as Me option (only if not already "Me")
        if original_speaker.lower() != "me":
            set_as_me_action = QAction("Set as Me", self)
            set_as_me_action.triggered.connect(
                lambda: self.set_as_me_requested.emit(original_speaker)
            )
            menu.addAction(set_as_me_action)

        menu.addSeparator()

        # Reassign this utterance to another speaker
        reassign_menu = menu.addMenu("Assign this line to")
        assert reassign_menu is not None

        # Get all unique speakers
        all_speakers = []
        for u in self._utterances:
            s = u.get("speaker", "Unknown")
            if s not in all_speakers:
                all_speakers.append(s)

        for s in all_speakers:
            if s != original_speaker:
                display_name = self._get_display_speaker(s)
                action = QAction(display_name, self)
                action.triggered.connect(
                    lambda checked, sp=s, idx=index: self._reassign_utterance(idx, sp)
                )
                reassign_menu.addAction(action)

        # New speaker option
        reassign_menu.addSeparator()
        new_speaker_action = QAction("+ New Speaker...", self)
        new_speaker_action.triggered.connect(lambda: self._reassign_to_new_speaker(index))
        reassign_menu.addAction(new_speaker_action)

        # Merge all utterances of this speaker with another (global operation)
        other_speakers = [s for s in all_speakers if s != original_speaker]
        if other_speakers:
            menu.addSeparator()
            merge_menu = menu.addMenu(f'Merge all "{speaker}" with')
            assert merge_menu is not None
            for other in other_speakers:
                other_display = self._get_display_speaker(other)
                merge_action = QAction(other_display, self)
                merge_action.triggered.connect(
                    lambda checked, target=other: self.merge_speakers_requested.emit(
                        original_speaker, target
                    )
                )
                merge_menu.addAction(merge_action)

        # Show menu at cursor
        menu.exec(bubble.speaker_label.mapToGlobal(bubble.speaker_label.rect().bottomLeft()))

    def _rename_speaker(self, current_name: str):
        """Rename a speaker globally."""
        # Find the original speaker name
        original = None
        for orig, display in self._speaker_names.items():
            if display == current_name:
                original = orig
                break
        if not original:
            original = current_name

        new_name = None
        dialog = SpeakerInputDialog(
            "Rename Speaker",
            f'Rename "{current_name}" to:',
            current_name,
            self._speaker_suggestions,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name = dialog.get_new_name()

        if new_name and new_name != current_name:
            self._speaker_names[original] = new_name

            # Update all bubbles with this speaker
            for i, u in enumerate(self._utterances):
                if u.get("speaker") == original:
                    color = self._speaker_colors.get(original, SPEAKER_COLORS[1])
                    self._bubbles[i].update_speaker(new_name, color)

            self.speaker_names_changed.emit(self._speaker_names)

    def _reassign_utterance(self, index: int, new_speaker: str):
        """Reassign a single utterance to a different speaker."""
        if index >= len(self._utterances):
            return

        self._utterances[index]["speaker"] = new_speaker

        # Rebuild all bubbles to reflect the change
        self._rebuild_bubbles()

        self.utterances_changed.emit(self._utterances)

    def _reassign_to_new_speaker(self, index: int):
        """Create a new speaker and assign utterance to them."""
        new_name = None
        dialog = SpeakerInputDialog(
            "New Speaker",
            "Enter new speaker name:",
            "",
            self._speaker_suggestions,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name = dialog.get_new_name()

        if new_name:
            # Assign a new color
            used_colors = set(self._speaker_colors.values())
            for color in SPEAKER_COLORS:
                if color not in used_colors:
                    self._speaker_colors[new_name] = color
                    break
            else:
                self._speaker_colors[new_name] = SPEAKER_COLORS[
                    len(self._speaker_colors) % len(SPEAKER_COLORS)
                ]

            self._reassign_utterance(index, new_name)

    def clear(self):
        """Clear the transcript view."""
        self._active_bubble = None
        self._utterances = []
        self._speaker_names = {}
        self._speaker_colors = {}
        for bubble in self._bubbles:
            bubble.deleteLater()
        self._bubbles = []

    def get_utterances(self) -> list[dict]:
        """Get current utterances (may have been edited)."""
        return self._utterances

    def get_speaker_names(self) -> dict[str, str]:
        """Get speaker name mapping."""
        return self._speaker_names

    def _apply_bubble_style(self, bubble: UtteranceBubble, active: bool = False):
        """Apply styling to a bubble, optionally as active."""
        original_speaker = self._utterances[bubble.index].get("speaker", "Unknown")
        color = self._speaker_colors.get(original_speaker, SPEAKER_COLORS[1])
        align = "left" if bubble.is_me else "right"
        border_side = "left" if bubble.is_me else "right"

        if active:
            bg_color = "#3a3a3a"  # Lighter background for active
            border_width = "4px"
        else:
            bg_color = "#2d2d2d"
            border_width = "3px"

        bubble.setStyleSheet(f"""
            UtteranceBubble {{
                background-color: {bg_color};
                border-{border_side}: {border_width} solid {color};
                border-radius: 8px;
                margin-{align}: 20px;
                margin-top: 4px;
                margin-bottom: 4px;
            }}
        """)

    def highlight_utterance_at_time(self, ms: int):
        """Highlight the utterance that contains the given time."""
        active_bubble = None
        for bubble in self._bubbles:
            # Find utterance matching playback time (assumes sequential)
            if bubble.start_time_ms is not None and ms >= bubble.start_time_ms and (bubble.end_time_ms is None or ms < bubble.end_time_ms):
                active_bubble = bubble
                break

        if active_bubble == self._active_bubble:
            return

        # Deactivate old bubble
        if self._active_bubble is not None:
            self._apply_bubble_style(self._active_bubble, active=False)

        # Activate new bubble
        if active_bubble is not None:
            self._apply_bubble_style(active_bubble, active=True)
            self.ensureWidgetVisible(active_bubble, 0, 50)

        self._active_bubble = active_bubble

    def _clear_highlights(self):
        """Clear all search highlights."""
        for bubble in self._bubbles:
            text = self._utterances[bubble.index].get("text", "")
            layout = bubble.layout()
            if layout is not None:
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item:
                        widget = item.widget()
                        if isinstance(widget, QLabel) and not isinstance(widget, ClickableLabel):
                            widget.setTextFormat(Qt.TextFormat.PlainText)
                            widget.setText(text)
                            break

    def highlight_search_term(self, term: str):
        """Highlight search term and scroll to first match."""
        if not term:
            return

        self._clear_highlights()
        term_lower = term.lower()
        first_match = None

        for bubble in self._bubbles:
            text = self._utterances[bubble.index].get("text", "")
            if term_lower in text.lower():
                if not first_match:
                    first_match = bubble

                highlighted_text = re.sub(
                    f"({re.escape(term)})",
                    r'<span style="background-color: #555500; color: #fff;">\1</span>',
                    text,
                    flags=re.IGNORECASE
                )

                # Find the QLabel inside the bubble
                layout = bubble.layout()
                if layout is not None:
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item:
                            widget = item.widget()
                            if isinstance(widget, QLabel) and not isinstance(widget, ClickableLabel):
                                widget.setTextFormat(Qt.TextFormat.RichText)
                                widget.setText(highlighted_text)
                                break

        if first_match:
            self.ensureWidgetVisible(first_match, 0, 50)
