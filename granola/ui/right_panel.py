"""Right panel - AI Chat for searching across meetings."""

import contextlib
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from granola.constants import CHAT_MAX_HISTORY, LAYOUT_MARGIN_SMALL

if TYPE_CHECKING:
    from granola.search.chat_worker import ChatWorker
    from granola.search.file_search import FileSearchManager
    from granola.storage.database import Database

logger = logging.getLogger("granola")


class ChatMessageWidget(QFrame):
    """Widget for displaying a single chat message."""

    def __init__(
        self,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._setup_ui(role, content, citations)

    def _setup_ui(self, role: str, content: str, citations: list[dict[str, Any]] | None) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Message content
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(content_label)

        # Citations if present
        if citations:
            # Count unique meetings (by title) and total passages
            unique_meetings = {c.get("title", "Unknown") for c in citations}
            meeting_count = len(unique_meetings)
            passage_count = len(citations)
            meeting_word = "meeting" if meeting_count == 1 else "meetings"
            passage_word = "passage" if passage_count == 1 else "passages"
            label_text = f"Sources: {meeting_count} {meeting_word}, {passage_count} {passage_word}"
            citations_label = QLabel(label_text)
            citations_label.setStyleSheet("color: #888; font-size: 11px;")
            layout.addWidget(citations_label)

        # Style based on role
        if role == "user":
            self.setStyleSheet(
                """
                ChatMessageWidget {
                    background-color: #3498db;
                    border-radius: 10px;
                    margin-left: 40px;
                    margin-right: 5px;
                }
                QLabel {
                    color: white;
                }
            """
            )
        else:
            self.setStyleSheet(
                """
                ChatMessageWidget {
                    background-color: #404040;
                    border-radius: 10px;
                    margin-left: 5px;
                    margin-right: 40px;
                }
                QLabel {
                    color: #eee;
                }
            """
            )


class RightPanel(QWidget):
    """AI Chat panel for searching across meetings."""

    def __init__(
        self,
        db: "Database | None" = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.db = db
        self._file_search: FileSearchManager | None = None
        self._chat_session_id = str(uuid.uuid4())
        self._chat_history: list[dict[str, str]] = []
        self._chat_worker: ChatWorker | None = None
        self._enabled = False
        self._setup_ui()

    def _create_placeholder(self) -> QLabel:
        """Create the placeholder label for empty chat."""
        placeholder = QLabel(
            "Ask questions about your meetings.\n\n"
            "Examples:\n"
            "• What action items came from last week?\n"
            "• What did we discuss about the API?\n"
            "• Summarize my meeting with Sarah"
        )
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #666; margin-top: 30px;")
        return placeholder

    def _clear_chat_widgets(self) -> None:
        """Remove all widgets from the chat layout."""
        while self.chat_layout.count() > 0:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _setup_ui(self) -> None:
        """Setup the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT_MARGIN_SMALL,
            LAYOUT_MARGIN_SMALL,
            LAYOUT_MARGIN_SMALL,
            LAYOUT_MARGIN_SMALL,
        )
        layout.setSpacing(LAYOUT_MARGIN_SMALL)

        # Header with status
        header_row = QHBoxLayout()
        header = QLabel("AI Assistant")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_row.addWidget(header)

        self.sync_status = QLabel("Not connected")
        self.sync_status.setStyleSheet("color: #888; font-size: 11px;")
        header_row.addWidget(self.sync_status)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Chat messages area (scrollable)
        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        self.chat_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_area.setStyleSheet("QScrollArea { border: none; }")

        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(8)
        self.chat_layout.setContentsMargins(10, 10, 10, 10)

        self.placeholder = self._create_placeholder()
        self.chat_layout.addWidget(self.placeholder)

        self.chat_area.setWidget(self.chat_widget)
        layout.addWidget(self.chat_area, stretch=1)

        # Input area
        input_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Ask about your meetings...")
        self.chat_input.setEnabled(False)
        self.chat_input.returnPressed.connect(self._send_message)
        self.chat_input.setStyleSheet(
            """
            QLineEdit {
                padding: 8px;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #333;
                color: #eee;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
            QLineEdit:disabled {
                background-color: #222;
                color: #666;
            }
        """
        )
        input_row.addWidget(self.chat_input, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_message)
        self.send_btn.setStyleSheet(
            """
            QPushButton {
                padding: 8px 16px;
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """
        )
        input_row.addWidget(self.send_btn)

        layout.addLayout(input_row)

        # Clear chat button
        self.clear_btn = QPushButton("New Chat")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._clear_chat)
        self.clear_btn.setStyleSheet(
            """
            QPushButton {
                padding: 6px;
                background-color: transparent;
                color: #888;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #333;
                color: #eee;
            }
            QPushButton:disabled {
                color: #555;
                border-color: #444;
            }
        """
        )
        layout.addWidget(self.clear_btn)

    def set_database(self, db: "Database") -> None:
        """Set the database reference."""
        self.db = db

    def set_file_search(self, file_search: "FileSearchManager") -> None:
        """Set the file search manager."""
        self._file_search = file_search

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the panel."""
        self._enabled = enabled
        self.chat_input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)

        if enabled:
            self.sync_status.setText("Connected")
            self.sync_status.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self.sync_status.setText("Not connected")
            self.sync_status.setStyleSheet("color: #888; font-size: 11px;")

    def _send_message(self) -> None:
        """Send user message and get response."""
        if not self._enabled or not self._file_search:
            return

        question = self.chat_input.text().strip()
        if not question:
            return

        # Clear input and disable during query
        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.send_btn.setEnabled(False)

        # Hide placeholder
        self.placeholder.hide()

        # Add user message to UI
        self._add_message("user", question)

        # Add to history
        self._chat_history.append({"role": "user", "content": question})

        # Save to database
        if self.db:
            self.db.save_chat_message(self._chat_session_id, "user", question)

        # Start chat worker
        from granola.search.chat_worker import ChatWorker

        self._chat_worker = ChatWorker(self._file_search, question, self._chat_history)
        self._chat_worker.response_ready.connect(self._on_response)
        self._chat_worker.error.connect(self._on_error)
        self._chat_worker.start()

    def _on_response(self, response: str, citations: list[dict[str, Any]]) -> None:
        """Handle chat response."""
        # Add assistant message to UI
        self._add_message("assistant", response, citations)

        # Add to history (use "model" for Gemini API compatibility)
        self._chat_history.append({"role": "model", "content": response})

        # Save to database
        if self.db:
            citations_json = json.dumps(citations) if citations else None
            self.db.save_chat_message(self._chat_session_id, "assistant", response, citations_json)

        # Re-enable input
        self.chat_input.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.chat_input.setFocus()

    def _on_error(self, error: str) -> None:
        """Handle chat error."""
        self._add_message("assistant", f"Error: {error}")
        self.chat_input.setEnabled(True)
        self.send_btn.setEnabled(True)

    def _add_message(
        self,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add a message to the chat area."""
        msg_widget = ChatMessageWidget(role, content, citations)
        self.chat_layout.addWidget(msg_widget)

        # Scroll to bottom after a brief delay to ensure layout is updated
        QTimer.singleShot(
            50,
            lambda: self.chat_area.verticalScrollBar().setValue(
                self.chat_area.verticalScrollBar().maximum()
            ),
        )

    def _clear_chat(self) -> None:
        """Clear chat and start new session."""
        self._clear_chat_widgets()
        self.placeholder = self._create_placeholder()
        self.chat_layout.addWidget(self.placeholder)
        self._chat_history.clear()

        # New session
        self._chat_session_id = str(uuid.uuid4())

    def load_chat_history(self, session_id: str) -> None:
        """Load chat history from a previous session."""
        if not self.db:
            return

        self._chat_session_id = session_id
        self._chat_history.clear()
        self._clear_chat_widgets()

        history = self.db.get_chat_history(session_id, CHAT_MAX_HISTORY)

        if history:
            for msg in history:
                role = msg["role"]
                content = msg["content"]
                citations = None
                if msg.get("citations"):
                    with contextlib.suppress(json.JSONDecodeError):
                        citations = json.loads(msg["citations"])

                self._add_message(role, content, citations)
                self._chat_history.append({"role": role, "content": content})
        else:
            self.placeholder = self._create_placeholder()
            self.chat_layout.addWidget(self.placeholder)
