"""Trim view - full trim UI with waveform, controls, and preview playback."""

import logging
from collections.abc import Sequence

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from quinoa.audio.trimmer import (
    AudioAnalysis,
    TrimRegion,
    analyse_audio,
    compute_trimmed_duration,
    trim_recording,
)
from quinoa.ui.waveform_widget import CutMarker, WaveformWidget

logger = logging.getLogger("quinoa")


class AnalysisWorker(QThread):
    """Background worker to analyse audio without blocking the UI."""

    finished = pyqtSignal(object)  # AudioAnalysis | None

    def __init__(self, audio_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._audio_path = audio_path

    def run(self) -> None:
        result = analyse_audio(self._audio_path)
        self.finished.emit(result)


class TrimWorker(QThread):
    """Background worker to apply trim to recording files."""

    finished = pyqtSignal(bool, float)  # success, new_duration

    def __init__(
        self,
        recording_dir: str,
        keep_regions: list[TrimRegion],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._recording_dir = recording_dir
        self._keep_regions = keep_regions

    def run(self) -> None:
        success = trim_recording(self._recording_dir, self._keep_regions)
        new_duration = compute_trimmed_duration(self._keep_regions)
        self.finished.emit(success, new_duration)


class TrimView(QWidget):
    """Complete trim UI for a recording.

    Provides waveform visualization, cut markers, silence suggestions,
    preview playback, and apply/reset controls.

    Signals:
        trim_applied: Emitted after a successful trim with the new duration.
    """

    trim_applied = pyqtSignal(float)  # new duration in seconds

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        # State
        self._recording_dir: str | None = None
        self._rec_id: str | None = None
        self._audio_path: str | None = None
        self._analysis: AudioAnalysis | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._trim_worker: TrimWorker | None = None
        self._original_duration: float = 0.0

        # Preview player
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_player_position)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Info bar
        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)

        self._status_label = QLabel("Loading waveform...")
        self._status_label.setStyleSheet("color: #888; font-size: 12px;")
        info_row.addWidget(self._status_label)

        info_row.addStretch()

        self._duration_label = QLabel()
        self._duration_label.setStyleSheet(
            "color: #e0e0e0; font-size: 12px; font-family: monospace;"
        )
        info_row.addWidget(self._duration_label)

        layout.addLayout(info_row)

        # Waveform
        self._waveform = WaveformWidget()
        self._waveform.setMinimumHeight(120)
        self._waveform.cuts_changed.connect(self._on_cuts_changed)
        self._waveform.position_clicked.connect(self._on_position_clicked)
        layout.addWidget(self._waveform)

        # Controls bar
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._suggest_btn = QPushButton("Suggest Cuts")
        self._suggest_btn.setToolTip("Auto-detect silence at start/end of recording")
        self._suggest_btn.clicked.connect(self._suggest_silence_cuts)
        self._suggest_btn.setEnabled(False)
        controls.addWidget(self._suggest_btn)

        self._add_cut_btn = QPushButton("Add Cut")
        self._add_cut_btn.setToolTip("Add a cut region in the center of the view")
        self._add_cut_btn.clicked.connect(self._waveform.add_cut_at_center)
        self._add_cut_btn.setEnabled(False)
        controls.addWidget(self._add_cut_btn)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setToolTip("Remove all cut markers")
        self._clear_btn.clicked.connect(self._waveform.clear_cuts)
        self._clear_btn.setEnabled(False)
        controls.addWidget(self._clear_btn)

        controls.addStretch()

        # Preview button
        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setToolTip("Play audio from clicked position")
        self._preview_btn.setCheckable(True)
        self._preview_btn.clicked.connect(self._toggle_preview)
        self._preview_btn.setEnabled(False)
        controls.addWidget(self._preview_btn)

        controls.addStretch()

        # Apply / Reset
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setToolTip("Clear all cuts")
        self._reset_btn.clicked.connect(self._reset)
        self._reset_btn.setEnabled(False)
        controls.addWidget(self._reset_btn)

        self._apply_btn = QPushButton("Apply Trim")
        self._apply_btn.setToolTip("Trim the recording (creates backup)")
        self._apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: palette(mid);
                color: palette(disabled-text);
            }
        """)
        self._apply_btn.clicked.connect(self._apply_trim)
        self._apply_btn.setEnabled(False)
        controls.addWidget(self._apply_btn)

        layout.addLayout(controls)

        # Push everything to the top
        layout.addStretch(1)

    # -- Public API ----------------------------------------------------------

    def load_recording(
        self,
        audio_path: str,
        recording_dir: str,
        rec_id: str,
        duration_seconds: float,
    ) -> None:
        """Load a recording for trimming.

        Args:
            audio_path: Path to the primary audio file (stereo mix or mic).
            recording_dir: Directory containing all recording files.
            rec_id: Recording ID in the database.
            duration_seconds: Original duration from the database.
        """
        self._stop_preview()
        self._audio_path = audio_path
        self._recording_dir = recording_dir
        self._rec_id = rec_id
        self._original_duration = duration_seconds
        self._analysis = None

        self._status_label.setText("Analysing audio...")
        self._duration_label.setText("")
        self._set_controls_enabled(False)

        # Start background analysis
        self._analysis_worker = AnalysisWorker(audio_path, self)
        self._analysis_worker.finished.connect(self._on_analysis_done)
        self._analysis_worker.start()

    def clear(self) -> None:
        """Clear the trim view."""
        self._stop_preview()
        self._waveform.set_waveform([], 0.0)
        self._status_label.setText("")
        self._duration_label.setText("")
        self._set_controls_enabled(False)
        self._analysis = None
        self._recording_dir = None
        self._rec_id = None

    # -- Slots ---------------------------------------------------------------

    def _on_analysis_done(self, analysis: AudioAnalysis | None) -> None:
        """Handle analysis completion."""
        self._analysis_worker = None

        if analysis is None:
            self._status_label.setText("Failed to analyse audio")
            return

        self._analysis = analysis
        silence_tuples = [(r.start_seconds, r.end_seconds) for r in analysis.silent_regions]
        self._waveform.set_waveform(analysis.waveform, analysis.duration_seconds, silence_tuples)

        n_silence = len(analysis.silent_regions)
        if n_silence > 0:
            total_silence = sum(r.duration for r in analysis.silent_regions)
            self._status_label.setText(
                f"{n_silence} silent region{'s' if n_silence != 1 else ''} "
                f"({total_silence:.0f}s total) | Scroll to zoom, Shift+scroll to pan"
            )
        else:
            self._status_label.setText("No silence detected | Scroll to zoom, Shift+scroll to pan")

        self._update_duration_label()
        self._set_controls_enabled(True)
        self._apply_btn.setEnabled(False)  # No cuts yet

        # Auto-suggest trimming post-meeting tail if audio file is significantly
        # longer than the recorded meeting duration (e.g. PipeWire kept capturing
        # system audio after the call ended).
        self._suggest_tail_cut(analysis.duration_seconds)

        # Load audio for preview
        if self._audio_path:
            self._player.setSource(QUrl.fromLocalFile(self._audio_path))

    def _on_cuts_changed(self) -> None:
        """Handle cut markers being added/moved/removed."""
        has_cuts = len(self._waveform.get_cuts()) > 0
        self._apply_btn.setEnabled(has_cuts)
        self._clear_btn.setEnabled(has_cuts)
        self._reset_btn.setEnabled(has_cuts)
        self._update_duration_label()

    def _on_position_clicked(self, seconds: float) -> None:
        """Handle click on waveform -- seek preview player."""
        if self._preview_btn.isChecked():
            self._player.setPosition(int(seconds * 1000))

    def _on_player_position(self, position_ms: int) -> None:
        """Update playhead from preview player."""
        self._waveform.set_playhead(position_ms / 1000.0)

    def _suggest_silence_cuts(self) -> None:
        """Auto-suggest cuts from detected silence regions."""
        if not self._analysis:
            return
        silence_tuples = [(r.start_seconds, r.end_seconds) for r in self._analysis.silent_regions]
        if not silence_tuples:
            self._status_label.setText("No silence detected to suggest cuts from")
            return
        self._waveform.suggest_cuts_from_silence(silence_tuples, edge_only=False)

    def _toggle_preview(self) -> None:
        """Toggle preview playback."""
        if self._preview_btn.isChecked():
            self._player.play()
        else:
            self._stop_preview()

    def _stop_preview(self) -> None:
        """Stop preview playback."""
        self._player.stop()
        self._preview_btn.setChecked(False)
        self._waveform.set_playhead(None)

    def _reset(self) -> None:
        """Clear all cuts."""
        self._waveform.clear_cuts()
        self._status_label.setText("Cuts cleared")

    def _apply_trim(self) -> None:
        """Apply the trim operation."""
        cuts = self._waveform.get_cuts()
        if not cuts or not self._recording_dir:
            return

        # Build keep regions from cuts
        keep_regions = self._compute_keep_regions(cuts)
        if not keep_regions:
            QMessageBox.warning(
                self,
                "Invalid Trim",
                "The cuts would remove the entire recording.",
            )
            return

        new_duration = compute_trimmed_duration(keep_regions)
        if new_duration < 1.0:
            QMessageBox.warning(
                self,
                "Too Short",
                "The trimmed recording would be less than 1 second.",
            )
            return

        # Confirm
        reply = QMessageBox.question(
            self,
            "Apply Trim",
            f"Trim recording from {self._format_time(self._original_duration)} "
            f"to {self._format_time(new_duration)}?\n\n"
            "Original files will be backed up with .pretrim extension.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable UI during trim
        self._set_controls_enabled(False)
        self._status_label.setText("Trimming...")
        self._stop_preview()

        self._trim_worker = TrimWorker(self._recording_dir, keep_regions, self)
        self._trim_worker.finished.connect(self._on_trim_done)
        self._trim_worker.start()

    def _on_trim_done(self, success: bool, new_duration: float) -> None:
        """Handle trim completion."""
        self._trim_worker = None

        if success:
            self._status_label.setText(
                f"Trim complete! {self._format_time(self._original_duration)} -> "
                f"{self._format_time(new_duration)}"
            )
            self._original_duration = new_duration
            self._waveform.clear_cuts()
            self.trim_applied.emit(new_duration)

            # Reload waveform with trimmed audio
            if self._audio_path and self._recording_dir and self._rec_id:
                self.load_recording(
                    self._audio_path,
                    self._recording_dir,
                    self._rec_id,
                    new_duration,
                )
        else:
            self._status_label.setText("Trim failed -- originals preserved")
            self._set_controls_enabled(True)

    # -- Helpers -------------------------------------------------------------

    # Minimum extra audio (seconds) beyond DB duration to trigger tail suggestion.
    _TAIL_THRESHOLD_SECONDS = 10.0

    def _suggest_tail_cut(self, file_duration: float) -> None:
        """Auto-suggest cutting post-meeting audio tail.

        If the audio file is significantly longer than the meeting's recorded
        duration (e.g. PipeWire kept capturing after the call ended), add a
        cut region covering the tail.
        """
        if self._original_duration <= 0:
            return

        tail_length = file_duration - self._original_duration
        if tail_length < self._TAIL_THRESHOLD_SECONDS:
            return

        # Add a cut from the recorded meeting end to the end of the file
        self._waveform.add_cut(self._original_duration, file_duration)

        tail_fmt = self._format_time(tail_length)
        logger.info(
            "Auto-suggested tail cut: %s of post-meeting audio (file=%s, meeting=%s)",
            tail_fmt,
            self._format_time(file_duration),
            self._format_time(self._original_duration),
        )

        # Update status to inform the user
        current = self._status_label.text()
        self._status_label.setText(f"{current} | Suggested {tail_fmt} tail cut")

    def _compute_keep_regions(self, cuts: Sequence[CutMarker]) -> list[TrimRegion]:
        """Convert cut markers into keep regions."""
        if not self._analysis:
            return []

        duration = self._analysis.duration_seconds
        # Sort cuts by start time
        sorted_cuts = sorted(cuts, key=lambda c: c.start_seconds)

        keep: list[TrimRegion] = []
        current = 0.0

        for cut in sorted_cuts:
            start = cut.start_seconds
            end = cut.end_seconds
            if start > current:
                keep.append(TrimRegion(current, start))
            current = max(current, end)

        if current < duration:
            keep.append(TrimRegion(current, duration))

        return keep

    def _update_duration_label(self) -> None:
        """Update the duration display."""
        if not self._analysis:
            return

        cuts = self._waveform.get_cuts()
        if cuts:
            keep_regions = self._compute_keep_regions(cuts)
            new_duration = compute_trimmed_duration(keep_regions)
            removed = self._original_duration - new_duration
            self._duration_label.setText(
                f"{self._format_time(new_duration)} (removing {self._format_time(removed)})"
            )
        else:
            self._duration_label.setText(self._format_time(self._original_duration))

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable all controls."""
        self._suggest_btn.setEnabled(enabled)
        self._add_cut_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        self._preview_btn.setEnabled(enabled)
        self._reset_btn.setEnabled(enabled)
        self._apply_btn.setEnabled(enabled)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as M:SS or H:MM:SS."""
        total = int(seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
