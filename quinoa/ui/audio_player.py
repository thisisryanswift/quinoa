"""Audio player widget for playback controls."""

from PyQt6.QtCore import Qt, QUrl, QTime
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QMenu,
)
from PyQt6.QtGui import QAction


class AudioPlayer(QFrame):
    """Audio player widget with playback controls."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AudioPlayer")
        self.setStyleSheet("""
            QFrame#AudioPlayer {
                background-color: #2d2d2d;
                border-radius: 8px;
                border: 1px solid #3d3d3d;
            }
            QLabel {
                color: #e0e0e0;
                font-family: monospace;
            }
            QSlider::groove:horizontal {
                border: 1px solid #3d3d3d;
                height: 4px;
                background: #1e1e1e;
                margin: 2px 0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #4a9eff;
                border: 1px solid #4a9eff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: #4a9eff;
                border-radius: 2px;
            }
        """)

        # Media Player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        # Signals
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.errorOccurred.connect(self._on_error)

        self._setup_ui()

        # State
        self._duration = 0
        self._seeking = False

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Top row: Controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(12)

        # Play/Pause Button
        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(32, 32)
        style = self.style()
        if style:
            self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4a9eff;
                border-radius: 16px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #3b8ce0;
            }}
        """)
        controls_layout.addWidget(self.play_btn)

        # Time Label
        self.time_label = QLabel("00:00 / 00:00")
        controls_layout.addWidget(self.time_label)

        # Slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.valueChanged.connect(self._on_slider_moved)
        controls_layout.addWidget(self.slider)

        # Speed Button
        self.speed_btn = QToolButton()
        self.speed_btn.setText("1.0x")
        self.speed_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.speed_btn.setStyleSheet("""
            QToolButton {
                color: #e0e0e0;
                background: transparent;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QToolButton:hover {
                background: #3d3d3d;
            }
        """)

        speed_menu = QMenu(self)
        for rate in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
            action = QAction(f"{rate}x", self)
            action.triggered.connect(lambda checked, r=rate: self.set_playback_rate(r))
            speed_menu.addAction(action)
        self.speed_btn.setMenu(speed_menu)
        controls_layout.addWidget(self.speed_btn)

        layout.addLayout(controls_layout)

    def load_audio(self, file_path: str):
        """Load an audio file."""
        self.stop()
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.play_btn.setEnabled(True)
        self.slider.setEnabled(True)

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def set_playback_rate(self, rate: float):
        """Set playback speed."""
        self.player.setPlaybackRate(rate)
        self.speed_btn.setText(f"{rate}x")

    def _on_state_changed(self, state):
        style = self.style()
        if not style:
            return

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        else:
            self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def _on_position_changed(self, position):
        if not self._seeking:
            self.slider.setValue(position)
        self._update_time_label(position, self._duration)

    def _on_duration_changed(self, duration):
        self._duration = duration
        self.slider.setRange(0, duration)
        self._update_time_label(self.player.position(), duration)

    def _update_time_label(self, current_ms, total_ms):
        current = QTime(0, 0).addMSecs(current_ms)
        total = QTime(0, 0).addMSecs(total_ms)

        fmt = "mm:ss"
        if total.hour() > 0:
            fmt = "h:mm:ss"

        self.time_label.setText(f"{current.toString(fmt)} / {total.toString(fmt)}")

    def _on_slider_pressed(self):
        self._seeking = True

    def _on_slider_released(self):
        self._seeking = False
        self.player.setPosition(self.slider.value())

    def _on_slider_moved(self, value):
        if self._seeking:
            self._update_time_label(value, self._duration)

    def _on_error(self):
        self.play_btn.setEnabled(False)
        self.slider.setEnabled(False)
        self.time_label.setText("Error loading audio")
