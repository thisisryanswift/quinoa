"""Calendar panel - Meetings-first navigation with calendar integration."""

import json
import logging
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from quinoa.calendar import is_authenticated
from quinoa.constants import (
    ICON_BULLET,
    ICON_CHECKMARK,
    ICON_CIRCLE_EMPTY,
    ICON_PLAY,
    LAYOUT_MARGIN_SMALL,
)
from quinoa.storage.database import Database

logger = logging.getLogger("quinoa")

# Meeting item types stored in UserRole+1
ITEM_TYPE_CALENDAR_EVENT = "calendar_event"
ITEM_TYPE_RECORDING = "recording"
ITEM_TYPE_HEADER = "header"


class CalendarPanel(QWidget):
    """Calendar-based navigation panel with meetings-first design."""

    # Signals
    meeting_selected = pyqtSignal(str)  # event_id for calendar events
    recording_selected = pyqtSignal(str)  # recording_id for recordings
    meeting_renamed = pyqtSignal(str, str)  # rec_id, new_title
    impromptu_meeting_requested = pyqtSignal()
    new_meeting_requested = pyqtSignal()  # Alias for compatibility
    settings_requested = pyqtSignal()

    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
        self._selected_id: str | None = None
        self._selected_type: str | None = None
        self._oldest_loaded_date: datetime | None = None
        self._loading_more = False
        self._calendar_connected = False  # Cached auth state for scroll performance

        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        """Setup the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT_MARGIN_SMALL, LAYOUT_MARGIN_SMALL, LAYOUT_MARGIN_SMALL, LAYOUT_MARGIN_SMALL
        )
        layout.setSpacing(LAYOUT_MARGIN_SMALL)

        # Meeting list with scroll detection
        self.meeting_list = QListWidget()
        self.meeting_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.meeting_list.customContextMenuRequested.connect(self._show_context_menu)
        self.meeting_list.itemClicked.connect(self._on_item_clicked)
        self.meeting_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.meeting_list.setWordWrap(True)  # Wrap long meeting names
        self.meeting_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Add spacing/padding for better readability (keeps native theme colors)
        self.meeting_list.setSpacing(2)
        self.meeting_list.setStyleSheet("QListWidget::item { padding: 6px 4px; }")

        # Connect scroll event for lazy loading
        self.meeting_list.verticalScrollBar().valueChanged.connect(self._on_scroll)

        layout.addWidget(self.meeting_list, stretch=1)

        # Impromptu Meeting button
        self.impromptu_btn = QPushButton("+ Impromptu Meeting")
        self.impromptu_btn.clicked.connect(self._on_impromptu_clicked)
        layout.addWidget(self.impromptu_btn)

        # Settings button at bottom
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

    def _add_section_header(self, label: str) -> None:
        """Add a section header (UPCOMING, TODAY, etc.)."""
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(Qt.ItemDataRole.UserRole + 1, ITEM_TYPE_HEADER)
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        item.setFont(font)
        item.setForeground(Qt.GlobalColor.gray)
        self.meeting_list.addItem(item)

    def _add_date_header(self, label: str) -> None:
        """Add a date group header."""
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(Qt.ItemDataRole.UserRole + 1, ITEM_TYPE_HEADER)
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        item.setFont(font)
        item.setForeground(Qt.GlobalColor.darkGray)
        self.meeting_list.addItem(item)

    def _to_local(self, dt: datetime) -> datetime:
        """Convert datetime to local time, handling both aware and naive datetimes."""
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt

    def _format_time(self, dt: datetime) -> str:
        """Format time as 9:30 AM (converting to local time if needed)."""
        local_dt = self._to_local(dt)
        return local_dt.strftime("%I:%M %p").lstrip("0")

    def _format_duration(self, seconds: float | None) -> str:
        """Format duration as '32 min'."""
        if not seconds:
            return ""
        mins = int(seconds // 60)
        return f"{mins} min"

    def _get_meeting_platform(self, meet_link: str | None) -> str:
        """Detect meeting platform from link."""
        return get_meeting_platform(meet_link)

    def _create_calendar_item(
        self,
        event: dict,
        is_upcoming: bool = False,
    ) -> QListWidgetItem:
        """Create a list item for a calendar event."""
        title = event["title"]
        start_time_raw = datetime.fromisoformat(event["start_time"])
        end_time_raw = datetime.fromisoformat(event["end_time"])
        meet_link = event.get("meet_link")
        recording_id = event.get("rec_id")
        rec_duration = event.get("rec_duration")

        # Convert to local naive datetimes for comparison with datetime.now()
        start_time = self._to_local(start_time_raw)
        end_time = self._to_local(end_time_raw)
        now = datetime.now()

        time_str = self._format_time(start_time_raw)
        platform = self._get_meeting_platform(meet_link)

        # Determine status
        if recording_id and rec_duration:
            duration_str = self._format_duration(rec_duration)
            status_prefix = f"{ICON_CHECKMARK} "
            detail = f"{time_str} {ICON_BULLET} {duration_str}"
        elif start_time <= now <= end_time:
            status_prefix = f"{ICON_PLAY} "
            detail = f"NOW {ICON_BULLET} {platform}" if platform else "NOW"
        elif is_upcoming:
            delta = start_time - now
            if delta.total_seconds() < 3600:
                mins = int(delta.total_seconds() // 60)
                time_until = f"in {mins} min"
            else:
                time_until = time_str
            status_prefix = ""
            detail = f"{time_until} {ICON_BULLET} {platform}" if platform else time_until
        else:
            status_prefix = f"{ICON_CIRCLE_EMPTY} "
            detail = time_str

        item = QListWidgetItem(f"{status_prefix}{title}\n{detail}")
        item.setData(Qt.ItemDataRole.UserRole, event["event_id"])
        item.setData(Qt.ItemDataRole.UserRole + 1, ITEM_TYPE_CALENDAR_EVENT)
        item.setData(Qt.ItemDataRole.UserRole + 2, recording_id)

        if not recording_id and start_time < now and not (start_time <= now <= end_time):
            item.setForeground(Qt.GlobalColor.darkGray)

        return item

    def _create_recording_item(self, rec: dict) -> QListWidgetItem:
        """Create a list item for an unlinked recording."""
        title = rec["title"]
        ts = rec["started_at"]
        duration = rec["duration_seconds"]

        try:
            dt = datetime.fromisoformat(ts)
            time_str = self._format_time(dt)
        except (ValueError, TypeError):
            time_str = str(ts)

        duration_str = self._format_duration(duration)
        detail = f"{time_str} {ICON_BULLET} {duration_str}" if duration_str else time_str

        item = QListWidgetItem(f"{ICON_CHECKMARK} {title}\n{detail}")
        item.setData(Qt.ItemDataRole.UserRole, rec["id"])
        item.setData(Qt.ItemDataRole.UserRole + 1, ITEM_TYPE_RECORDING)

        return item

    def refresh(self):
        """Refresh the panel - show calendar events if connected, otherwise recordings."""
        # Disable updates during bulk load for smoother UI
        self.meeting_list.setUpdatesEnabled(False)
        try:
            self.meeting_list.clear()
            self._oldest_loaded_date = None

            # Cache auth state so we don't hit keyring on every scroll event
            self._calendar_connected = is_authenticated()

            if self._calendar_connected:
                self._load_calendar_view()
            else:
                self._load_recordings_view()
        finally:
            self.meeting_list.setUpdatesEnabled(True)

    def _load_calendar_view(self):
        """Load the meetings-first calendar view."""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start.replace(hour=23, minute=59, second=59)

        events = self.db.get_calendar_events(today_start, today_end)

        upcoming = []
        past = []

        for event in events:
            start_time = self._to_local(datetime.fromisoformat(event["start_time"]))
            if start_time > now:
                upcoming.append(event)
            else:
                past.append(event)

        # UPCOMING section
        if upcoming:
            self._add_section_header("UPCOMING")
            for event in upcoming:
                item = self._create_calendar_item(event, is_upcoming=True)
                self.meeting_list.addItem(item)
                self._restore_selection(event["event_id"], ITEM_TYPE_CALENDAR_EVENT, item)

        # TODAY section - past calendar events + unlinked recordings
        self._add_section_header("TODAY")

        # Add past calendar events from today
        for event in reversed(past):
            item = self._create_calendar_item(event, is_upcoming=False)
            self.meeting_list.addItem(item)
            self._restore_selection(event["event_id"], ITEM_TYPE_CALENDAR_EVENT, item)

        # Add unlinked recordings from today
        linked_ids = {e.get("rec_id") for e in events if e.get("rec_id")}
        todays_recordings = self._get_recordings_for_date(today_start, today_end)
        for rec in todays_recordings:
            if rec["id"] not in linked_ids:
                item = self._create_recording_item(rec)
                self.meeting_list.addItem(item)
                self._restore_selection(rec["id"], ITEM_TYPE_RECORDING, item)

        # Track oldest loaded date for lazy loading
        self._oldest_loaded_date = today_start

        # Load initial history in one batch (2 weeks)
        self._load_initial_history(14)

    def _load_recordings_view(self):
        """Load the traditional recordings-only view (when calendar not connected)."""
        recordings = self.db.get_recordings()
        current_group = None

        for rec in recordings:
            ts = rec["started_at"]
            try:
                dt = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                dt = None

            if dt:
                group = self._get_date_group(dt)
                if group != current_group:
                    current_group = group
                    self._add_date_header(group)

            item = self._create_recording_item(rec)
            self.meeting_list.addItem(item)
            self._restore_selection(rec["id"], ITEM_TYPE_RECORDING, item)

    def _get_date_group(self, dt: datetime) -> str:
        """Get the date group label for a datetime."""
        today = datetime.now().date()
        rec_date = dt.date()

        if rec_date == today:
            return "Today"
        elif rec_date == today - timedelta(days=1):
            return "Yesterday"
        elif rec_date >= today - timedelta(days=7):
            return dt.strftime("%A")  # Day name
        else:
            return dt.strftime("%b %d, %Y")  # Nov 27, 2025

    def _restore_selection(self, item_id: str, item_type: str, item: QListWidgetItem):
        """Restore selection state for an item."""
        if self._selected_id == item_id and self._selected_type == item_type:
            item.setSelected(True)
            self.meeting_list.setCurrentItem(item)

    def _on_scroll(self, value: int):
        """Handle scroll - load more history when near bottom."""
        if self._loading_more:
            return

        scrollbar = self.meeting_list.verticalScrollBar()
        if value >= scrollbar.maximum() - 50:  # Near bottom
            self._load_more_history()

    def _load_initial_history(self, days: int) -> None:
        """Load multiple days of history in a single batch for better performance."""
        if not self._oldest_loaded_date:
            return

        end_date = self._oldest_loaded_date
        start_date = end_date - timedelta(days=days)

        # Limit to 30 days max
        max_history = datetime.now() - timedelta(days=30)
        if start_date < max_history:
            start_date = max_history

        # Fetch all data for the range in two queries (much faster than per-day)
        all_events = self.db.get_calendar_events(start_date, end_date)
        all_recordings = self.db.get_recordings_in_range(start_date, end_date)

        # Group by date
        events_by_date: dict[str, list[dict]] = {}
        for event in all_events:
            date_key = event["start_time"][:10]  # YYYY-MM-DD
            if date_key not in events_by_date:
                events_by_date[date_key] = []
            events_by_date[date_key].append(event)

        recordings_by_date: dict[str, list[dict]] = {}
        for rec in all_recordings:
            date_key = rec["started_at"][:10]  # YYYY-MM-DD
            if date_key not in recordings_by_date:
                recordings_by_date[date_key] = []
            recordings_by_date[date_key].append(rec)

        # Iterate through each day and add content
        current_date = end_date - timedelta(days=1)  # Start from yesterday
        while current_date >= start_date:
            date_key = current_date.strftime("%Y-%m-%d")
            day_events = events_by_date.get(date_key, [])
            day_recordings = recordings_by_date.get(date_key, [])

            if day_events or day_recordings:
                # Add date header
                date_str = self._get_date_group(current_date)
                self._add_date_header(date_str)

                # Add calendar events
                for event in reversed(day_events):
                    item = self._create_calendar_item(event, is_upcoming=False)
                    self.meeting_list.addItem(item)

                # Add unlinked recordings
                linked_ids = {e.get("rec_id") for e in day_events if e.get("rec_id")}
                for rec in day_recordings:
                    if rec["id"] not in linked_ids:
                        item = self._create_recording_item(rec)
                        self.meeting_list.addItem(item)
                        self._restore_selection(rec["id"], ITEM_TYPE_RECORDING, item)

            current_date -= timedelta(days=1)

        # Update oldest loaded date
        self._oldest_loaded_date = start_date

    def _load_more_history(self):
        """Load more historical calendar events and recordings."""
        if not self._oldest_loaded_date or self._loading_more:
            return

        # Check if we've hit the limit
        max_history = datetime.now() - timedelta(days=30)
        if self._oldest_loaded_date <= max_history:
            return

        self._loading_more = True

        # Disable updates during bulk add
        self.meeting_list.setUpdatesEnabled(False)
        try:
            # Load the previous day
            end = self._oldest_loaded_date
            start = end - timedelta(days=1)

            events = self.db.get_calendar_events(start, end)
            recordings = self._get_recordings_for_date(start, end)

            # Only add content if there's something to show
            if events or recordings:
                # Add date header
                date_str = self._get_date_group(start)
                self._add_date_header(date_str)

                # Add calendar events (reversed for chronological order within day)
                for event in reversed(events):
                    item = self._create_calendar_item(event, is_upcoming=False)
                    self.meeting_list.addItem(item)

                # Add unlinked recordings from this date
                linked_ids = {e.get("rec_id") for e in events if e.get("rec_id")}
                for rec in recordings:
                    if rec["id"] not in linked_ids:
                        item = self._create_recording_item(rec)
                        self.meeting_list.addItem(item)
                        self._restore_selection(rec["id"], ITEM_TYPE_RECORDING, item)

            # Always advance the date, even if nothing to show
            self._oldest_loaded_date = start

        finally:
            self.meeting_list.setUpdatesEnabled(True)
            self._loading_more = False

    def _get_recordings_for_date(self, start: datetime, end: datetime) -> list[dict]:
        """Get recordings within a date range."""
        return self.db.get_recordings_in_range(start, end)

    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle item click."""
        item_type = item.data(Qt.ItemDataRole.UserRole + 1)
        item_id = item.data(Qt.ItemDataRole.UserRole)

        if item_type == ITEM_TYPE_HEADER:
            return

        self._selected_id = item_id
        self._selected_type = item_type

        if item_type == ITEM_TYPE_CALENDAR_EVENT:
            # Check if it has a linked recording
            recording_id = item.data(Qt.ItemDataRole.UserRole + 2)
            if recording_id:
                self.recording_selected.emit(recording_id)
            else:
                self.meeting_selected.emit(item_id)
        elif item_type == ITEM_TYPE_RECORDING:
            self.recording_selected.emit(item_id)

    def _show_context_menu(self, position):
        """Show context menu for items."""
        item = self.meeting_list.itemAt(position)
        if not item:
            return

        item_type = item.data(Qt.ItemDataRole.UserRole + 1)
        if item_type == ITEM_TYPE_HEADER:
            return

        menu = QMenu(self)

        if item_type == ITEM_TYPE_RECORDING:
            # Existing recording actions
            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(lambda: self._rename_recording(item))
            menu.addAction(rename_action)

            delete_action = QAction("Delete", self)
            delete_action.triggered.connect(lambda: self._delete_recording(item))
            menu.addAction(delete_action)

        elif item_type == ITEM_TYPE_CALENDAR_EVENT:
            recording_id = item.data(Qt.ItemDataRole.UserRole + 2)
            if recording_id:
                # Has recording - show recording actions
                rename_action = QAction("Rename Recording", self)
                rename_action.triggered.connect(
                    lambda: self._rename_recording_by_id(recording_id, item)
                )
                menu.addAction(rename_action)

                delete_action = QAction("Delete Recording", self)
                delete_action.triggered.connect(
                    lambda: self._delete_recording_by_id(recording_id, item)
                )
                menu.addAction(delete_action)
            else:
                # No recording yet
                event_id = item.data(Qt.ItemDataRole.UserRole)
                event = self.db.get_calendar_event(event_id)
                if event:
                    # Show attendees as info
                    attendees_json = event.get("attendees")
                    if attendees_json:
                        try:
                            attendees = json.loads(attendees_json)
                            if attendees:
                                attendee_names = [
                                    a.get("name", a.get("email", "")) for a in attendees[:5]
                                ]
                                info_action = QAction(
                                    f"Attendees: {', '.join(attendee_names)}", self
                                )
                                info_action.setEnabled(False)
                                menu.addAction(info_action)
                        except json.JSONDecodeError:
                            pass

        menu.exec(self.meeting_list.viewport().mapToGlobal(position))

    def _rename_recording(self, item: QListWidgetItem):
        """Rename a recording from its list item."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self._rename_recording_by_id(rec_id, item)

    def _rename_recording_by_id(self, rec_id: str, item: QListWidgetItem):
        """Rename a recording by its ID."""
        rec = self.db.get_recording(rec_id)
        if not rec:
            return

        current_title = rec["title"]
        new_title, ok = QInputDialog.getText(
            self, "Rename Recording", "New Title:", text=current_title
        )

        if ok and new_title:
            try:
                self.db.update_recording_title(rec_id, new_title)
                self.refresh()
                self.meeting_renamed.emit(rec_id, new_title)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to rename recording: {e}")

    def _delete_recording(self, item: QListWidgetItem):
        """Delete a recording from its list item."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self._delete_recording_by_id(rec_id, item)

    def _delete_recording_by_id(self, rec_id: str, item: QListWidgetItem):
        """Delete a recording by its ID."""
        rec = self.db.get_recording(rec_id)
        if not rec:
            return

        title = rec["title"]
        reply = QMessageBox.question(
            self,
            "Delete Recording",
            f"Are you sure you want to delete '{title}'?\n\n"
            "This will remove the recording and all associated data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_recording(rec_id)
                if self._selected_id == rec_id:
                    self._selected_id = None
                    self._selected_type = None
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete recording: {e}")

    def _on_impromptu_clicked(self):
        """Handle impromptu meeting button click."""
        self.clear_selection()
        self.impromptu_meeting_requested.emit()
        self.new_meeting_requested.emit()  # For compatibility

    def select_meeting(self, rec_id: str):
        """Programmatically select a recording by ID."""
        for i in range(self.meeting_list.count()):
            item = self.meeting_list.item(i)
            if not item:
                continue
            item_type = item.data(Qt.ItemDataRole.UserRole + 1)

            if item_type == ITEM_TYPE_RECORDING:
                if item.data(Qt.ItemDataRole.UserRole) == rec_id:
                    self.meeting_list.setCurrentItem(item)
                    self._selected_id = rec_id
                    self._selected_type = ITEM_TYPE_RECORDING
                    break
            elif (
                item_type == ITEM_TYPE_CALENDAR_EVENT
                and item.data(Qt.ItemDataRole.UserRole + 2) == rec_id
            ):
                self.meeting_list.setCurrentItem(item)
                self._selected_id = item.data(Qt.ItemDataRole.UserRole)
                self._selected_type = ITEM_TYPE_CALENDAR_EVENT
                break

    def clear_selection(self):
        """Clear the current selection."""
        self.meeting_list.clearSelection()
        self._selected_id = None
        self._selected_type = None

    @property
    def selected_recording_id(self) -> str | None:
        """Get the currently selected recording ID (for compatibility)."""
        if self._selected_type == ITEM_TYPE_RECORDING:
            return self._selected_id
        elif self._selected_type == ITEM_TYPE_CALENDAR_EVENT:
            # Return the linked recording ID if any
            for i in range(self.meeting_list.count()):
                item = self.meeting_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == self._selected_id:
                    return item.data(Qt.ItemDataRole.UserRole + 2)
        return None


def get_meeting_platform(meet_link: str | None, full_name: bool = False) -> str:
    """Detect meeting platform from link.

    Args:
        meet_link: The video meeting URL
        full_name: If True, return full platform name (e.g. "Google Meet")
                   If False, return short name (e.g. "Meet")
    """
    if not meet_link:
        return ""
    if "meet.google.com" in meet_link:
        return "Google Meet" if full_name else "Meet"
    if "zoom.us" in meet_link:
        return "Zoom"
    if "teams.microsoft.com" in meet_link:
        return "Microsoft Teams" if full_name else "Teams"
    return "Video"
