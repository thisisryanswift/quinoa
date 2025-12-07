"""Left panel - Navigation with meeting list and settings."""

import logging
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from quinoa.constants import LAYOUT_MARGIN_SMALL
from quinoa.storage.database import Database
from quinoa.ui.styles import MEETING_LIST_STYLE

logger = logging.getLogger("quinoa")


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

        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        """Setup the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT_MARGIN_SMALL, LAYOUT_MARGIN_SMALL, LAYOUT_MARGIN_SMALL, LAYOUT_MARGIN_SMALL
        )
        layout.setSpacing(LAYOUT_MARGIN_SMALL)

        # Meeting list
        self.meeting_list = QListWidget()
        self.meeting_list.setStyleSheet(MEETING_LIST_STYLE)
        self.meeting_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.meeting_list.customContextMenuRequested.connect(self._show_context_menu)
        self.meeting_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.meeting_list, stretch=1)

        # New Meeting button
        self.new_meeting_btn = QPushButton("+ New Meeting")
        self.new_meeting_btn.clicked.connect(self._on_new_meeting_clicked)
        layout.addWidget(self.new_meeting_btn)

        # Settings button at bottom
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

    def _show_context_menu(self, position):
        """Show context menu for meeting item."""
        item = self.meeting_list.itemAt(position)
        if not item:
            return

        menu = QMenu(self)

        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self._rename_recording(item))
        menu.addAction(rename_action)

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self._delete_recording(item))
        menu.addAction(delete_action)

        menu.exec(self.meeting_list.viewport().mapToGlobal(position))

    def _rename_recording(self, item: QListWidgetItem):
        """Rename a recording."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        current_text = item.text().split("\n")[0]  # Extract title
        # Remove duration if present
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
        """Delete a recording after confirmation."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        title = item.text().split("\n")[0]
        # Remove duration if present
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
                # Clear selection if this was selected
                if self._selected_rec_id == rec_id:
                    self._selected_rec_id = None
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete recording: {e}")

    def _get_date_group(self, dt: datetime) -> str:
        """Get the date group label for a datetime."""
        today = datetime.now().date()
        rec_date = dt.date()

        if rec_date == today:
            return "Today"
        elif rec_date == today - timedelta(days=1):
            return "Yesterday"
        elif rec_date >= today - timedelta(days=7):
            return dt.strftime("%A")  # Day name (Monday, Tuesday, etc.)
        else:
            return dt.strftime("%b %d, %Y")  # Nov 27, 2025

    def _add_date_header(self, label: str) -> None:
        """Add a date group header to the list."""
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # Non-selectable
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        item.setFont(font)
        item.setForeground(Qt.GlobalColor.gray)
        self.meeting_list.addItem(item)

    def refresh(self):
        """Refresh the meeting list from database."""
        current_selection = self._selected_rec_id
        self.meeting_list.clear()

        try:
            recordings = self.db.get_recordings()
            current_group = None

            for rec in recordings:
                # Parse timestamp
                ts = rec["started_at"]
                try:
                    dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    dt = None

                # Add date group header if needed
                if dt:
                    group = self._get_date_group(dt)
                    if group != current_group:
                        current_group = group
                        self._add_date_header(group)
                    time_str = dt.strftime("%I:%M %p").lstrip("0")  # 9:30 AM
                else:
                    time_str = str(ts)

                # Format duration
                duration = rec["duration_seconds"]
                duration_str = ""
                if duration:
                    mins = int(duration // 60)
                    duration_str = f" • {mins} min"

                # Create item with title and time
                item = QListWidgetItem(f"{rec['title']}\n{time_str}{duration_str}")
                item.setData(Qt.ItemDataRole.UserRole, rec["id"])
                self.meeting_list.addItem(item)

                # Restore selection
                if rec["id"] == current_selection:
                    item.setSelected(True)
                    self.meeting_list.setCurrentItem(item)

        except Exception as e:
            logger.error("Error refreshing meeting list: %s", e)

    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle meeting selection."""
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        self._selected_rec_id = rec_id
        self.meeting_selected.emit(rec_id)

    def select_meeting(self, rec_id: str):
        """Programmatically select a meeting by ID."""
        for i in range(self.meeting_list.count()):
            item = self.meeting_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == rec_id:
                self.meeting_list.setCurrentItem(item)
                self._selected_rec_id = rec_id
                break

    def _on_new_meeting_clicked(self):
        """Handle new meeting button click."""
        self.clear_selection()
        self.new_meeting_requested.emit()

    def clear_selection(self):
        """Clear the current meeting selection."""
        self.meeting_list.clearSelection()
        self._selected_rec_id = None

    @property
    def selected_recording_id(self) -> str | None:
        """Get the currently selected recording ID."""
        return self._selected_rec_id
