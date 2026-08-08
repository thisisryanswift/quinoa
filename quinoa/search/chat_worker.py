"""Background thread for chat queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from google.genai import errors
from PyQt6.QtCore import QThread, pyqtSignal

from quinoa.search.file_search import FileSearchError, FileSearchManager

if TYPE_CHECKING:
    from quinoa.ui.right_panel import MeetingContext


class ChatWorker(QThread):
    """Background thread for chat queries to File Search."""

    # ``response_ready`` and ``error`` carry the job outcome.  ``done`` is
    # emitted unconditionally from ``finally`` for safe process-lifetime cleanup.
    response_ready = pyqtSignal(str, list)  # response, citations
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(
        self,
        file_search: FileSearchManager,
        question: str,
        history: list[dict[str, str]],
        meeting_context: MeetingContext | None = None,
    ):
        super().__init__()
        self.file_search = file_search
        self.question = question
        self.history = history
        self.meeting_context = meeting_context

    def cancel(self) -> None:
        """Cooperatively cancel the query.

        ChatWorker does not own a per-worker HTTP client (it uses the shared
        FileSearchManager), so we only request interruption.
        """
        self.requestInterruption()

    def run(self) -> None:
        """Execute the chat query."""
        try:
            response, citations = self.file_search.query(
                self.question,
                chat_history=self.history,
                meeting_context=self.meeting_context,
            )

            if self.isInterruptionRequested():
                return

            self.response_ready.emit(response, citations)
        except (FileSearchError, errors.APIError, httpx.HTTPError) as e:
            if not self.isInterruptionRequested():
                logger = logging.getLogger("quinoa")
                logger.warning("Chat query failed: %s", e)
                self.error.emit(str(e))
        except Exception as e:
            if not self.isInterruptionRequested():
                logger = logging.getLogger("quinoa")
                logger.exception("Unexpected chat error")
                self.error.emit(f"Unexpected error: {e}")
        finally:
            self.done.emit()
