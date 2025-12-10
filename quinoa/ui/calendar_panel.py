"""Calendar panel - Meetings-first navigation with calendar integration."""

import json
import logging
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
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


class FolderTree(QTreeWidget):
    """Custom TreeWidget to handle drag and drop."""

    # Signal: item_id, new_folder_id (None for root/uncategorized depending on logic)
    item_moved_to_folder = pyqtSignal(str, str)

    def dropEvent(self, event: QDropEvent | None):
        if not event:
            return
        # Perform the default move
        super().dropEvent(event)

        # Iterate over selected items (the ones being dragged)
        for item in self.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                continue

            # We only care about recordings moving
            if data.startswith("rec:"):
                rec_id = data.split(":", 1)[1]
                parent = item.parent()

                folder_id = None
                if parent:
                    parent_data = parent.data(0, Qt.ItemDataRole.UserRole)
                    if parent_data and parent_data.startswith("folder:"):
                        fid = parent_data.split(":", 1)[1]
                        if fid != "uncategorized":
                            folder_id = fid

                self.item_moved_to_folder.emit(rec_id, folder_id)


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

        # Toggle Buttons (Today / History)
        toggle_layout = QHBoxLayout()
        self.btn_today = QPushButton("Today")
        self.btn_today.setCheckable(True)
        self.btn_today.setChecked(True)
        self.btn_today.clicked.connect(lambda: self._switch_view(0))

        self.btn_history = QPushButton("History")
        self.btn_history.setCheckable(True)
        self.btn_history.clicked.connect(lambda: self._switch_view(1))

        toggle_layout.addWidget(self.btn_today)
        toggle_layout.addWidget(self.btn_history)
        layout.addLayout(toggle_layout)

        # Stacked View
        self.view_stack = QStackedWidget()
        layout.addWidget(self.view_stack, stretch=1)

        # Page 0: Meeting List (Today) - Wrapper widget? No, list widget directly
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

        self.view_stack.addWidget(self.meeting_list)

        # Page 1: History Page Container
        self.history_page = QWidget()
        history_layout = QVBoxLayout(self.history_page)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(LAYOUT_MARGIN_SMALL)

        # Search Bar
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Filter meetings...")
        self.search_bar.textChanged.connect(self._filter_history)
        history_layout.addWidget(self.search_bar)

        # Folder Tree
        self.folder_tree = FolderTree()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setDragEnabled(True)
        self.folder_tree.setAcceptDrops(True)
        self.folder_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.folder_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.folder_tree.item_moved_to_folder.connect(self._on_item_moved_to_folder)

        history_layout.addWidget(self.folder_tree)
        self.view_stack.addWidget(self.history_page)

        # Buttons Layout
        self.action_layout = QHBoxLayout()

        # New Folder (History only)
        self.new_folder_btn = QPushButton("+ Folder")
        self.new_folder_btn.clicked.connect(self._create_folder)
        self.new_folder_btn.setVisible(False)
        self.action_layout.addWidget(self.new_folder_btn)

        # Impromptu Meeting button
        self.impromptu_btn = QPushButton("+ Impromptu Meeting")
        self.impromptu_btn.clicked.connect(self._on_impromptu_clicked)
        self.action_layout.addWidget(self.impromptu_btn)

        layout.addLayout(self.action_layout)

        # Settings button at bottom
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

    def _switch_view(self, index: int):
        self.view_stack.setCurrentIndex(index)
        self.btn_today.setChecked(index == 0)
        self.btn_history.setChecked(index == 1)
        self.new_folder_btn.setVisible(index == 1)

        # Refresh if switching to History for the first time or to ensure freshness
        if index == 1:
            self._refresh_history_tree()

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
        # Only refresh list if visible
        if self.view_stack.currentIndex() == 0:
            self._refresh_today_view()
        else:
            self._refresh_history_tree()

    def _refresh_today_view(self):
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

    def _refresh_history_tree(self):
        """Refresh the folder tree (History view)."""
        current_selection = self._selected_id
        self.folder_tree.clear()

        # Reset search filter
        self.search_bar.clear()

        try:
            # Get data
            folders = self.db.get_folders()
            recordings = self.db.get_recordings()

            # Build folder map
            folder_map: dict[str, QTreeWidgetItem] = {}

            # 1. Create Folder Items
            for folder in folders:
                item = QTreeWidgetItem([folder["name"]])
                item.setData(0, Qt.ItemDataRole.UserRole, f"folder:{folder['id']}")
                item.setFlags(
                    item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDropEnabled
                )
                # Store sort order if needed
                folder_map[folder["id"]] = item

            # Parent folder items
            root = self.folder_tree.invisibleRootItem()
            for folder in folders:
                item = folder_map[folder["id"]]
                parent_id = folder["parent_id"]
                if parent_id and parent_id in folder_map:
                    folder_map[parent_id].addChild(item)
                else:
                    root.addChild(item)
                item.setExpanded(True)  # Expand by default for now

            # 2. Add Recordings
            uncategorized_item = QTreeWidgetItem(["Uncategorized"])
            uncategorized_item.setData(0, Qt.ItemDataRole.UserRole, "folder:uncategorized")
            uncategorized_item.setFlags(uncategorized_item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            has_uncategorized = False

            for rec in recordings:
                # Format text
                ts = rec["started_at"]
                try:
                    dt = datetime.fromisoformat(ts)
                    time_str = dt.strftime("%b %d %I:%M %p").lstrip("0")
                except:
                    time_str = ""

                title = f"{rec['title']} ({time_str})"
                item = QTreeWidgetItem([title])
                item.setData(0, Qt.ItemDataRole.UserRole, f"rec:{rec['id']}")
                item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsDragEnabled
                )

                folder_id = rec.get("folder_id")
                if folder_id and folder_id in folder_map:
                    folder_map[folder_id].addChild(item)
                else:
                    uncategorized_item.addChild(item)
                    has_uncategorized = True

                # Restore selection
                if rec["id"] == current_selection:
                    item.setSelected(True)
                    self.folder_tree.setCurrentItem(item)

            if has_uncategorized:
                root.addChild(uncategorized_item)
                uncategorized_item.setExpanded(True)

        except Exception as e:
            logger.error("Error refreshing folder tree: %s", e)

    def _filter_history(self, text: str):
        """Filter the history tree."""
        search_text = text.lower().strip()
        root = self.folder_tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._filter_recursive(root.child(i), search_text)

    def _filter_recursive(self, item: QTreeWidgetItem, text: str) -> bool:
        """Recursively filter tree items."""
        # Check if item matches
        item_text = item.text(0).lower()
        matches = text in item_text

        # Check children
        child_matches = False
        for i in range(item.childCount()):
            if self._filter_recursive(item.child(i), text):
                child_matches = True

        # If item matches or any child matches, show it
        should_show = matches or child_matches
        item.setHidden(not should_show)

        # If showing because of child or match, expand if there is text
        if should_show and text:
            item.setExpanded(True)

        return should_show

    def _on_item_moved_to_folder(self, rec_id: str, folder_id: str | None):
        """Handle item dropped into a folder."""
        try:
            self.db.set_recording_folder(rec_id, folder_id)
        except Exception as e:
            logger.error("Error moving recording: %s", e)
            self._refresh_history_tree()  # Revert on error

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree selection."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data.startswith("rec:"):
            rec_id = data.split(":", 1)[1]
            self._selected_id = rec_id
            self._selected_type = ITEM_TYPE_RECORDING
            self.recording_selected.emit(rec_id)
        else:
            # Folder clicked
            pass

    def _show_tree_context_menu(self, position):
        item = self.folder_tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        menu = QMenu(self)
        if data.startswith("rec:"):
            rec_id = data.split(":", 1)[1]

            # Move to folder submenu
            move_menu = menu.addMenu("Move to Folder")
            folders = self.db.get_folders()

            # Add Uncategorized option
            uncat_action = QAction("Uncategorized", self)
            uncat_action.triggered.connect(lambda: self._move_recording(rec_id, None))
            move_menu.addAction(uncat_action)
            move_menu.addSeparator()

            for folder in folders:
                action = QAction(folder["name"], self)
                action.triggered.connect(lambda f=folder: self._move_recording(rec_id, f["id"]))
                move_menu.addAction(action)

            menu.addSeparator()

            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(lambda: self._rename_recording_from_tree(item))
            menu.addAction(rename_action)

            delete_action = QAction("Delete", self)
            delete_action.triggered.connect(lambda: self._delete_recording_from_tree(item))
            menu.addAction(delete_action)

        elif data.startswith("folder:"):
            if data == "folder:uncategorized":
                return  # Cannot modify uncategorized

            folder_id = data.split(":", 1)[1]

            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(lambda: self._rename_folder(folder_id, item.text(0)))
            menu.addAction(rename_action)

            delete_action = QAction("Delete", self)
            delete_action.triggered.connect(lambda: self._delete_folder(folder_id))
            menu.addAction(delete_action)

        menu.exec(self.folder_tree.viewport().mapToGlobal(position))

    def _create_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder Name:")
        if ok and name:
            import uuid

            folder_id = str(uuid.uuid4())
            try:
                self.db.create_folder(folder_id, name)
                self._refresh_history_tree()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create folder: {e}")

    def _rename_folder(self, folder_id: str, current_name: str):
        new_name, ok = QInputDialog.getText(self, "Rename Folder", "New Name:", text=current_name)
        if ok and new_name:
            try:
                self.db.update_folder(folder_id, name=new_name)
                self._refresh_history_tree()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to rename folder: {e}")

    def _delete_folder(self, folder_id: str):
        reply = QMessageBox.question(
            self,
            "Delete Folder",
            "Are you sure you want to delete this folder?\nMeetings inside will be moved to Uncategorized.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_folder(folder_id)
                self._refresh_history_tree()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete folder: {e}")

    def _move_recording(self, rec_id: str, folder_id: str | None):
        try:
            self.db.set_recording_folder(rec_id, folder_id)
            self._refresh_history_tree()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to move recording: {e}")

    def _rename_recording_from_tree(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("rec:"):
            return
        rec_id = data.split(":", 1)[1]

        current_text = item.text(0)
        if "(" in current_text:
            current_text = current_text.rsplit(" (", 1)[0]

        new_title, ok = QInputDialog.getText(
            self, "Rename Recording", "New Title:", text=current_text
        )

        if ok and new_title:
            try:
                self.db.update_recording_title(rec_id, new_title)
                self._refresh_history_tree()
                self.meeting_renamed.emit(rec_id, new_title)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to rename recording: {e}")

    def _delete_recording_from_tree(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("rec:"):
            return
        rec_id = data.split(":", 1)[1]
        self._delete_recording_by_id(rec_id, None)  # Reuse existing delete logic but refresh tree
        # The existing _delete_recording_by_id refreshes the whole panel which is fine
        # But we need to ensure it refreshes the tree if we are in tree mode
        # Let's just override the refresh call or let it be.
        # Actually _delete_recording_by_id calls self.refresh(), which now handles both views.

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
                    title = event.get("title", "Unknown")
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

                    menu.addSeparator()

                    hide_action = QAction("Hide from list", self)
                    hide_action.setStatusTip("Hide this meeting from the calendar list")
                    hide_action.triggered.connect(
                        lambda: self._hide_calendar_event(event_id, title)
                    )
                    menu.addAction(hide_action)

        menu.exec(self.meeting_list.viewport().mapToGlobal(position))

    def _hide_calendar_event(self, event_id: str, title: str):
        """Hide a calendar event from the list."""
        reply = QMessageBox.question(
            self,
            "Hide Meeting",
            f"Are you sure you want to hide '{title}'?\n\n"
            "You won't see it in the list anymore, but it will remain in your Google Calendar.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.db.set_calendar_event_hidden(event_id, True)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to hide meeting: {e}")

    def _rename_recording(self, item: QListWidgetItem):
        """Rename a recording from its list item."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self._rename_recording_by_id(rec_id, item)

    def _rename_recording_by_id(self, rec_id: str, item: QListWidgetItem | None):
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

    def _delete_recording_by_id(self, rec_id: str, item: QListWidgetItem | None):
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
            self.recording_selected.emit(self._selected_id)
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
