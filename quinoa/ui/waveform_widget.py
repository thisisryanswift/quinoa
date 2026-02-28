"""Waveform display widget with interactive trim handles.

Renders an audio waveform with draggable cut markers for trimming recordings.
Cut regions are shown as dimmed overlays. Silence regions are highlighted.
"""

import logging
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger("quinoa")

# Colours
COLOR_WAVEFORM = QColor("#4a9eff")
COLOR_WAVEFORM_CUT = QColor("#4a9eff").darker(250)
COLOR_BACKGROUND = QColor("#1e1e1e")
COLOR_CUT_OVERLAY = QColor(230, 60, 60, 60)
COLOR_CUT_HANDLE = QColor("#e74c3c")
COLOR_CUT_HANDLE_HOVER = QColor("#ff6b6b")
COLOR_SILENCE = QColor(255, 200, 50, 12)  # Very subtle highlight
COLOR_PLAYHEAD = QColor("#2ecc71")
COLOR_CENTERLINE = QColor(255, 255, 255, 25)

HANDLE_WIDTH_PX = 3
HANDLE_HIT_WIDTH_PX = 10  # Wider hit target for easier grabbing
MIN_REGION_SECONDS = 0.5  # Minimum gap between handles


@dataclass
class CutMarker:
    """A pair of handles defining a region to cut."""

    start_seconds: float
    end_seconds: float


class WaveformWidget(QWidget):
    """Interactive waveform display with cut markers.

    Signals:
        cuts_changed: Emitted when cut markers are added, removed, or moved.
        position_clicked: Emitted when user clicks on waveform (position in seconds).
    """

    cuts_changed = pyqtSignal()
    position_clicked = pyqtSignal(float)  # seconds

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMaximumHeight(200)
        self.setMinimumWidth(200)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        # Data
        self._waveform: list[float] = []
        self._duration_seconds: float = 0.0
        self._silence_regions: list[tuple[float, float]] = []  # (start_s, end_s)
        self._cuts: list[CutMarker] = []
        self._playhead_seconds: float | None = None

        # Zoom / scroll
        self._view_start: float = 0.0  # Visible range start (seconds)
        self._view_end: float = 0.0  # Visible range end (seconds)

        # Interaction state
        self._dragging: _DragState | None = None
        self._region_dragging: _RegionDragState | None = None
        self._hover_handle: _HandleRef | None = None
        self._hover_cut: CutMarker | None = None  # For body hover (move cursor)

    # -- Public API ----------------------------------------------------------

    def set_waveform(
        self,
        waveform: list[float],
        duration_seconds: float,
        silence_regions: list[tuple[float, float]] | None = None,
    ) -> None:
        """Load waveform data for display."""
        self._waveform = waveform
        self._duration_seconds = duration_seconds
        self._silence_regions = silence_regions or []
        self._cuts.clear()
        self._view_start = 0.0
        self._view_end = duration_seconds
        self._playhead_seconds = None
        self.update()

    def set_playhead(self, seconds: float | None) -> None:
        """Update the playhead position (or None to hide it)."""
        self._playhead_seconds = seconds
        self.update()

    def get_cuts(self) -> list[CutMarker]:
        """Return current cut markers."""
        return list(self._cuts)

    def add_cut(self, start: float, end: float) -> None:
        """Add a cut marker programmatically."""
        start = max(0.0, start)
        end = min(self._duration_seconds, end)
        if end - start < MIN_REGION_SECONDS:
            return
        self._cuts.append(CutMarker(start, end))
        self._cuts.sort(key=lambda c: c.start_seconds)
        self.cuts_changed.emit()
        self.update()

    def remove_cut(self, index: int) -> None:
        """Remove a cut marker by index."""
        if 0 <= index < len(self._cuts):
            self._cuts.pop(index)
            self.cuts_changed.emit()
            self.update()

    def clear_cuts(self) -> None:
        """Remove all cuts."""
        self._cuts.clear()
        self.cuts_changed.emit()
        self.update()

    def add_cut_at_center(self) -> None:
        """Add a cut in the center of the visible view."""
        view_duration = self._view_end - self._view_start
        center = self._view_start + view_duration / 2
        cut_width = min(view_duration * 0.1, 10.0)  # 10% of view or 10s
        cut_width = max(cut_width, MIN_REGION_SECONDS * 2)
        start = max(0.0, center - cut_width / 2)
        end = min(self._duration_seconds, center + cut_width / 2)
        self.add_cut(start, end)

    def suggest_cuts_from_silence(
        self,
        silence_regions: list[tuple[float, float]],
        edge_only: bool = False,
    ) -> None:
        """Auto-suggest cuts from silence regions.

        Args:
            silence_regions: List of (start, end) silence regions.
            edge_only: If True, only suggest cuts at start/end of recording.
        """
        self.clear_cuts()
        for start, end in silence_regions:
            if edge_only:
                is_start = start < 1.0
                is_end = end > self._duration_seconds - 1.0
                if not (is_start or is_end):
                    continue
            if end - start >= MIN_REGION_SECONDS:
                self._cuts.append(CutMarker(start, end))
        self._cuts.sort(key=lambda c: c.start_seconds)
        self.cuts_changed.emit()
        self.update()

    @property
    def duration_seconds(self) -> float:
        return self._duration_seconds

    # -- Coordinate conversion -----------------------------------------------

    def _seconds_to_x(self, seconds: float) -> float:
        """Convert time in seconds to widget x coordinate."""
        view_duration = self._view_end - self._view_start
        if view_duration <= 0:
            return 0.0
        return (seconds - self._view_start) / view_duration * self.width()

    def _x_to_seconds(self, x: float) -> float:
        """Convert widget x coordinate to time in seconds."""
        view_duration = self._view_end - self._view_start
        if self.width() <= 0:
            return self._view_start
        return self._view_start + x / self.width() * view_duration

    # -- Painting ------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, COLOR_BACKGROUND)

        if not self._waveform or self._duration_seconds <= 0:
            painter.setPen(QPen(QColor("#666")))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No waveform data")
            painter.end()
            return

        # Center line
        center_y = h / 2.0

        # Draw silence regions (behind waveform)
        for start_s, end_s in self._silence_regions:
            x1 = self._seconds_to_x(start_s)
            x2 = self._seconds_to_x(end_s)
            if x2 < 0 or x1 > w:
                continue
            painter.fillRect(QRectF(x1, 0, x2 - x1, h), COLOR_SILENCE)

        # Draw waveform bars
        self._draw_waveform(painter, w, h, center_y)

        # Center line (on top of waveform for reference)
        painter.setPen(QPen(COLOR_CENTERLINE, 1))
        painter.drawLine(QPointF(0, center_y), QPointF(w, center_y))

        # Draw cut overlays
        for cut in self._cuts:
            x1 = self._seconds_to_x(cut.start_seconds)
            x2 = self._seconds_to_x(cut.end_seconds)
            if x2 < 0 or x1 > w:
                continue
            painter.fillRect(QRectF(x1, 0, x2 - x1, h), COLOR_CUT_OVERLAY)

            # Draw handles
            for handle_x in [x1, x2]:
                is_hovered = (
                    self._hover_handle is not None
                    and self._hover_handle.cut is cut
                    and (
                        (self._hover_handle.is_end and handle_x == x2)
                        or (not self._hover_handle.is_end and handle_x == x1)
                    )
                )
                color = COLOR_CUT_HANDLE_HOVER if is_hovered else COLOR_CUT_HANDLE
                painter.fillRect(
                    QRectF(handle_x - HANDLE_WIDTH_PX / 2, 0, HANDLE_WIDTH_PX, h),
                    color,
                )

        # Draw playhead
        if self._playhead_seconds is not None:
            px = self._seconds_to_x(self._playhead_seconds)
            if 0 <= px <= w:
                painter.setPen(QPen(COLOR_PLAYHEAD, 2))
                painter.drawLine(QPointF(px, 0), QPointF(px, h))

        painter.end()

    def _draw_waveform(self, painter: QPainter, w: int, h: int, center_y: float) -> None:
        """Draw waveform bars, dimming those inside cut regions."""
        n_bins = len(self._waveform)
        if n_bins == 0:
            return

        # Map visible time range to bin indices
        bin_duration = self._duration_seconds / n_bins
        start_bin = max(0, int(self._view_start / bin_duration))
        end_bin = min(n_bins, int(self._view_end / bin_duration) + 1)

        bar_width = max(1.0, w / max(1, end_bin - start_bin))

        for i in range(start_bin, end_bin):
            amp = self._waveform[i]
            bin_time = i * bin_duration

            # Check if this bin is inside a cut region
            is_cut = any(cut.start_seconds <= bin_time <= cut.end_seconds for cut in self._cuts)

            color = COLOR_WAVEFORM_CUT if is_cut else COLOR_WAVEFORM
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))

            x = self._seconds_to_x(bin_time)
            bar_h = amp * (h / 2.0 - 2)  # Leave 2px margin
            painter.drawRect(QRectF(x, center_y - bar_h, bar_width, bar_h * 2))

    # -- Mouse interaction ---------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        x = event.position().x()
        handle = self._find_handle_at(x)

        if handle:
            # Start dragging a handle
            self._dragging = _DragState(handle=handle)
        else:
            # Check if clicking inside a cut region body
            seconds = self._x_to_seconds(x)
            seconds = max(0.0, min(self._duration_seconds, seconds))
            cut = self._find_cut_at(x)
            if cut:
                # Start dragging the entire region
                self._region_dragging = _RegionDragState(
                    cut=cut,
                    grab_offset=seconds - cut.start_seconds,
                )
            else:
                # Click on waveform -> set playhead
                self.position_clicked.emit(seconds)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return

        x = event.position().x()

        if self._dragging:
            seconds = self._x_to_seconds(x)
            seconds = max(0.0, min(self._duration_seconds, seconds))
            self._move_handle(self._dragging.handle, seconds)
            self.update()
        elif self._region_dragging:
            seconds = self._x_to_seconds(x)
            seconds = max(0.0, min(self._duration_seconds, seconds))
            self._move_region(self._region_dragging, seconds)
            self.update()
        else:
            # Update hover state: handles take priority over cut body
            handle = self._find_handle_at(x)
            cut_body = self._find_cut_at(x) if handle is None else None

            needs_update = False
            if handle != self._hover_handle:
                self._hover_handle = handle
                needs_update = True
            if cut_body != self._hover_cut:
                self._hover_cut = cut_body
                needs_update = True

            if needs_update:
                if handle:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif cut_body:
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._dragging:
            self._dragging = None
            self.cuts_changed.emit()
        if self._region_dragging:
            self._region_dragging = None
            self.cuts_changed.emit()

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        """Zoom with scroll wheel, pan with Shift+scroll."""
        if event is None or self._duration_seconds <= 0:
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Pan
            view_duration = self._view_end - self._view_start
            pan_amount = view_duration * 0.1 * (-1 if delta > 0 else 1)
            new_start = self._view_start + pan_amount
            new_end = self._view_end + pan_amount
            if new_start < 0:
                new_end -= new_start
                new_start = 0
            if new_end > self._duration_seconds:
                new_start -= new_end - self._duration_seconds
                new_end = self._duration_seconds
            self._view_start = max(0.0, new_start)
            self._view_end = min(self._duration_seconds, new_end)
        else:
            # Zoom toward cursor
            cursor_seconds = self._x_to_seconds(event.position().x())
            view_duration = self._view_end - self._view_start
            zoom_factor = 0.8 if delta > 0 else 1.25
            new_duration = max(2.0, view_duration * zoom_factor)
            new_duration = min(new_duration, self._duration_seconds)

            # Keep cursor position stable
            cursor_frac = (
                (cursor_seconds - self._view_start) / view_duration if view_duration > 0 else 0.5
            )
            new_start = cursor_seconds - cursor_frac * new_duration
            new_end = new_start + new_duration
            if new_start < 0:
                new_end -= new_start
                new_start = 0
            if new_end > self._duration_seconds:
                new_start -= new_end - self._duration_seconds
                new_end = self._duration_seconds
            self._view_start = max(0.0, new_start)
            self._view_end = min(self._duration_seconds, new_end)

        self.update()
        event.accept()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.update()

    # -- Handle finding / moving ---------------------------------------------

    def _find_handle_at(self, x: float) -> "_HandleRef | None":
        """Find a handle near the given x coordinate."""
        for cut in self._cuts:
            start_x = self._seconds_to_x(cut.start_seconds)
            end_x = self._seconds_to_x(cut.end_seconds)

            if abs(x - start_x) <= HANDLE_HIT_WIDTH_PX:
                return _HandleRef(cut=cut, is_end=False)
            if abs(x - end_x) <= HANDLE_HIT_WIDTH_PX:
                return _HandleRef(cut=cut, is_end=True)

        return None

    def _find_cut_at(self, x: float) -> CutMarker | None:
        """Find a cut region whose body contains the given x coordinate."""
        for cut in self._cuts:
            start_x = self._seconds_to_x(cut.start_seconds)
            end_x = self._seconds_to_x(cut.end_seconds)
            # Only match the interior, not within the handle hit zones
            if start_x + HANDLE_HIT_WIDTH_PX < x < end_x - HANDLE_HIT_WIDTH_PX:
                return cut
        return None

    def _move_handle(self, handle: "_HandleRef", seconds: float) -> None:
        """Move a handle to a new position, clamping to valid range."""
        cut = handle.cut
        if handle.is_end:
            cut.end_seconds = max(cut.start_seconds + MIN_REGION_SECONDS, seconds)
            cut.end_seconds = min(cut.end_seconds, self._duration_seconds)
        else:
            cut.start_seconds = min(cut.end_seconds - MIN_REGION_SECONDS, seconds)
            cut.start_seconds = max(cut.start_seconds, 0.0)

    def _move_region(self, state: "_RegionDragState", cursor_seconds: float) -> None:
        """Slide an entire cut region, preserving its width."""
        cut = state.cut
        width = cut.end_seconds - cut.start_seconds
        new_start = cursor_seconds - state.grab_offset

        # Clamp to recording bounds
        new_start = max(0.0, new_start)
        new_start = min(self._duration_seconds - width, new_start)

        cut.start_seconds = new_start
        cut.end_seconds = new_start + width


@dataclass
class _HandleRef:
    """Reference to a specific handle on a cut marker."""

    cut: CutMarker
    is_end: bool  # True for end handle, False for start


@dataclass
class _DragState:
    """Active drag operation on a handle."""

    handle: _HandleRef


@dataclass
class _RegionDragState:
    """Active drag operation on a cut region body."""

    cut: CutMarker
    grab_offset: float  # Offset from cut start to where the user grabbed
