"""Left panel - Navigation with meeting list and settings."""

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
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from quinoa.constants import LAYOUT_MARGIN_SMALL
from quinoa.storage.database import Database

logger = logging.getLogger("quinoa")


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


class LeftPanel(QWidget):
    """Navigation panel with meeting list and settings button."""

    meeting_selected = pyqtSignal(str)
    meeting_renamed = pyqtSignal(str, str)  # rec_id, new_title
    new_meeting_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
        self._selected_rec_id: str | None = None
        self._drag_start_position = None

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

        # Page 0: Meeting List (Today)
        self.meeting_list = QListWidget()
        self.meeting_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.meeting_list.customContextMenuRequested.connect(self._show_list_context_menu)
        self.meeting_list.itemClicked.connect(self._on_list_item_clicked)
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

        # New Folder / Meeting Buttons
        self.action_layout = QHBoxLayout()
        self.new_folder_btn = QPushButton("+ Folder")
        self.new_folder_btn.clicked.connect(self._create_folder)
        self.new_folder_btn.setVisible(False)  # Only on History tab

        self.new_meeting_btn = QPushButton("+ New Meeting")
        self.new_meeting_btn.clicked.connect(self._on_new_meeting_clicked)

        self.action_layout.addWidget(self.new_folder_btn)
        self.action_layout.addWidget(self.new_meeting_btn)
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
        self.refresh()

    def refresh(self):
        """Refresh the visible view."""
        if self.view_stack.currentIndex() == 0:
            self._refresh_today_list()
        else:
            self._refresh_history_tree()

    def _refresh_today_list(self):
        """Refresh the meeting list (Today view)."""
        current_selection = self._selected_rec_id
        self.meeting_list.clear()

        try:
            # For "Today" view, we show upcoming + today's meetings + maybe recent ones?
            # The requirement says: "Today: Current view (upcoming + today's meetings, chronological)"

            recordings = self.db.get_recordings()
            current_group = None

            for rec in recordings:
                # Parse timestamp
                ts = rec["started_at"]
                try:
                    dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    dt = None

                # Add date group header
                if dt:
                    group = self._get_date_group(dt)
                    if group != current_group:
                        current_group = group
                        self._add_date_header(group)
                    time_str = dt.strftime("%I:%M %p").lstrip("0")
                else:
                    time_str = str(ts)

                # Format duration
                duration = rec["duration_seconds"]
                duration_str = ""
                if duration:
                    mins = int(duration // 60)
                    duration_str = f" • {mins} min"

                # Create item
                item = QListWidgetItem(f"{rec['title']}\n{time_str}{duration_str}")
                item.setData(Qt.ItemDataRole.UserRole, rec["id"])
                self.meeting_list.addItem(item)

                # Restore selection
                if rec["id"] == current_selection:
                    item.setSelected(True)
                    self.meeting_list.setCurrentItem(item)

        except Exception as e:
            logger.error("Error refreshing meeting list: %s", e)

    def _refresh_history_tree(self):
        """Refresh the folder tree (History view)."""
        current_selection = self._selected_rec_id
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
            self.refresh()  # Revert on error

    def _get_date_group(self, dt: datetime) -> str:
        """Get the date group label for a datetime."""
        today = datetime.now().date()
        rec_date = dt.date()

        if rec_date == today:
            return "Today"
        elif rec_date == today - timedelta(days=1):
            return "Yesterday"
        elif rec_date >= today - timedelta(days=7):
            return dt.strftime("%A")
        else:
            return dt.strftime("%b %d, %Y")

    def _add_date_header(self, label: str) -> None:
        """Add a date group header to the list."""
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        item.setFont(font)
        item.setForeground(Qt.GlobalColor.gray)
        self.meeting_list.addItem(item)

    # ==================== Interaction Handlers ====================

    def _on_list_item_clicked(self, item: QListWidgetItem):
        """Handle list selection."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self._selected_rec_id = rec_id
        self.meeting_selected.emit(rec_id)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree selection."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data.startswith("rec:"):
            rec_id = data.split(":", 1)[1]
            self._selected_rec_id = rec_id
            self.meeting_selected.emit(rec_id)
        else:
            # Folder clicked
            pass

    def select_meeting(self, rec_id: str):
        """Programmatically select a meeting by ID."""
        self._selected_rec_id = rec_id
        # We need to find it in the current view
        if self.view_stack.currentIndex() == 0:
            # List View
            for i in range(self.meeting_list.count()):
                item = self.meeting_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == rec_id:
                    self.meeting_list.setCurrentItem(item)
                    break
        else:
            # Tree View
            iterator = QTreeWidgetItemIterator(self.folder_tree)
            while iterator.value():
                item = iterator.value()
                if item.data(0, Qt.ItemDataRole.UserRole) == f"rec:{rec_id}":
                    self.folder_tree.setCurrentItem(item)
                    item.setSelected(True)
                    # Expand parents
                    parent = item.parent()
                    while parent:
                        parent.setExpanded(True)
                        parent = parent.parent()
                    break
                iterator += 1

    def _on_new_meeting_clicked(self):
        self.clear_selection()
        self.new_meeting_requested.emit()

    def clear_selection(self):
        self.meeting_list.clearSelection()
        self.folder_tree.clearSelection()
        self._selected_rec_id = None

    @property
    def selected_recording_id(self) -> str | None:
        return self._selected_rec_id

    # ==================== Context Menus ====================

    def _show_list_context_menu(self, position):
        item = self.meeting_list.itemAt(position)
        if not item:
            return

        # Check if it's a date header (no user data)
        if not item.data(Qt.ItemDataRole.UserRole):
            return

        self._show_recording_context_menu(position, self.meeting_list, item)

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

    def _show_recording_context_menu(self, position, widget, item):
        """Shared context menu for recording items."""
        menu = QMenu(self)

        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self._rename_recording(item))
        menu.addAction(rename_action)

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self._delete_recording(item))
        menu.addAction(delete_action)

        menu.exec(widget.viewport().mapToGlobal(position))

    # ==================== Action Implementations ====================

    def _create_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder Name:")
        if ok and name:
            import uuid

            folder_id = str(uuid.uuid4())
            try:
                self.db.create_folder(folder_id, name)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create folder: {e}")

    def _rename_folder(self, folder_id: str, current_name: str):
        new_name, ok = QInputDialog.getText(self, "Rename Folder", "New Name:", text=current_name)
        if ok and new_name:
            try:
                self.db.update_folder(folder_id, name=new_name)
                self.refresh()
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
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete folder: {e}")

    def _move_recording(self, rec_id: str, folder_id: str | None):
        try:
            self.db.set_recording_folder(rec_id, folder_id)
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to move recording: {e}")

    def _rename_recording(self, item: QListWidgetItem):
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        current_text = item.text().split("\n")[0]
        if "(" in current_text:
            current_text = current_text.rsplit(" (", 1)[0]

        new_title, ok = QInputDialog.getText(
            self, "Rename Recording", "New Title:", text=current_text
        )

        if ok and new_title:
            try:
                self.db.update_recording_title(rec_id, new_title)
                self.refresh()
                self.meeting_renamed.emit(rec_id, new_title)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to rename recording: {e}")

    def _delete_recording(self, item: QListWidgetItem):
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self._confirm_delete_recording(rec_id, item.text().split("\n")[0])

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
                self.refresh()
                self.meeting_renamed.emit(rec_id, new_title)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to rename recording: {e}")

    def _delete_recording_from_tree(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not data.startswith("rec:"):
            return
        rec_id = data.split(":", 1)[1]
        self._confirm_delete_recording(rec_id, item.text(0))

    def _confirm_delete_recording(self, rec_id: str, title: str):
        if "(" in title:
            title = title.rsplit(" (", 1)[0]

        reply = QMessageBox.question(
            self,
            "Delete Recording",
            f"Are you sure you want to delete '{title}'?\n\nThis will remove the recording and all associated data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_recording(rec_id)
                if self._selected_rec_id == rec_id:
                    self._selected_rec_id = None
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete recording: {e}")
