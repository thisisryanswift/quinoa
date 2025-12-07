"""Background thread for chat queries."""

from PyQt6.QtCore import QThread, pyqtSignal

from quinoa.search.file_search import FileSearchError, FileSearchManager


class ChatWorker(QThread):
    """Background thread for chat queries to File Search."""

    response_ready = pyqtSignal(str, list)  # response, citations
    error = pyqtSignal(str)

    def __init__(
        self,
        file_search: FileSearchManager,
        question: str,
        history: list[dict[str, str]],
    ):
        super().__init__()
        self.file_search = file_search
        self.question = question
        self.history = history

    def run(self) -> None:
        """Execute the chat query."""
        try:
            response, citations = self.file_search.query(self.question, chat_history=self.history)
            self.response_ready.emit(response, citations)
        except FileSearchError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")
