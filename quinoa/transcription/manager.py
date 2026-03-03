import logging

from PyQt6.QtCore import QObject, pyqtSignal

from quinoa.config import config
from quinoa.storage.database import Database
from quinoa.ui.transcribe_worker import TranscribeWorker
from quinoa.ui.transcript_handler import (
    parse_transcription_result,
    utterances_to_json,
)

logger = logging.getLogger("quinoa")


class TranscriptionManager(QObject):
    """Global manager for transcription jobs.

    Handles queueing, parallel execution, and database persistence
    for transcription tasks.
    """

    # Signals
    job_started = pyqtSignal(str)  # rec_id
    job_finished = pyqtSignal(str, str)  # rec_id, transcript_json
    job_failed = pyqtSignal(str, str)  # rec_id, error_message

    def __init__(self, db: Database, parent: QObject | None = None):
        super().__init__(parent)
        self.db = db
        self._active_jobs: dict[str, TranscribeWorker] = {}

    def submit(self, rec_id: str, session_dir: str):
        """Submit a new transcription job."""
        if rec_id in self._active_jobs:
            logger.debug("Transcription already in progress for %s", rec_id)
            return

        if not config.get("api_key"):
            self.job_failed.emit(rec_id, "Gemini API key not configured.")
            return

        logger.info("Starting transcription job for %s", rec_id)

        worker = TranscribeWorker(session_dir, rec_id)
        worker.finished.connect(lambda result: self._on_worker_finished(rec_id, result))
        worker.error.connect(lambda error: self._on_worker_error(rec_id, error))

        self._active_jobs[rec_id] = worker
        worker.start()
        self.job_started.emit(rec_id)

    def is_running(self, rec_id: str) -> bool:
        """Check if a job is currently running for a recording."""
        return rec_id in self._active_jobs

    def cancel(self, rec_id: str):
        """Cancel a running transcription job."""
        worker = self._active_jobs.pop(rec_id, None)
        if worker:
            worker.cancel()
            worker.wait()
            worker.deleteLater()
            logger.info("Cancelled transcription for %s", rec_id)

    def cancel_all(self):
        """Cancel all running transcription jobs."""
        if not self._active_jobs:
            return

        logger.info("Cancelling all active transcription jobs...")
        # Create a list of keys to avoid modification during iteration
        for rec_id in list(self._active_jobs.keys()):
            self.cancel(rec_id)

    def _on_worker_finished(self, rec_id: str, json_str: str):
        """Handle worker completion and persist results."""
        worker = self._active_jobs.pop(rec_id, None)
        if not worker:
            return

        worker.deleteLater()

        try:
            # Parse and format for DB
            result = parse_transcription_result(json_str)
            utterances = result.get("utterances", [])
            utterances_json = utterances_to_json(utterances) if utterances else None

            # Save to DB
            self.db.save_transcript(
                rec_id, result["transcript"], result["summary"], utterances_json
            )

            if not result.get("parse_error"):
                self.db.save_action_items(rec_id, result.get("action_items", []))

            # Update status to 'transcribed'
            self.db.update_recording_status(rec_id, status="transcribed")

            logger.info("Transcription finished and saved for %s", rec_id)
            self.job_finished.emit(rec_id, json_str)

        except Exception as e:
            logger.error("Failed to save transcript for %s: %s", rec_id, e)
            self.job_failed.emit(rec_id, f"Failed to save results: {str(e)}")

    def _on_worker_error(self, rec_id: str, error_msg: str):
        """Handle worker error."""
        worker = self._active_jobs.pop(rec_id, None)
        if not worker:
            return  # Cancelled — ignore stale signal

        worker.deleteLater()
        logger.error("Transcription failed for %s: %s", rec_id, error_msg)
        self.job_failed.emit(rec_id, error_msg)
