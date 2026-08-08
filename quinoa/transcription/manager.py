import logging

from PyQt6.QtCore import QObject, pyqtSignal

from quinoa.calendar.utils import parse_attendee_names
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
    for transcription tasks.  Keeps strong references to active workers
    and uses cooperative cancellation without ``QThread.terminate()``.
    """

    # Signals
    job_started = pyqtSignal(str)  # rec_id
    job_finished = pyqtSignal(str, str)  # rec_id, transcript_json
    job_partial = pyqtSignal(str, str)  # rec_id, transcript_json (recovered)
    job_failed = pyqtSignal(str, str)  # rec_id, error_message

    def __init__(self, db: Database, parent: QObject | None = None):
        super().__init__(parent)
        self.db = db
        self._active_jobs: dict[str, TranscribeWorker] = {}
        # Workers stay here until their unconditional ``done`` signal fires,
        # preventing a running QThread from being destroyed while blocked.
        self._stashed_workers: dict[str, TranscribeWorker] = {}

    def submit(self, rec_id: str, session_dir: str):
        """Submit a new transcription job."""
        if rec_id in self._active_jobs or rec_id in self._stashed_workers:
            logger.debug("Transcription already in progress for %s", rec_id)
            return

        if not config.get("api_key"):
            self.job_failed.emit(rec_id, "Gemini API key not configured.")
            return

        # Fetch metadata for prompt hinting
        rec = self.db.get_recording(rec_id)
        title = rec.get("title") if rec else None

        attendees: list[str] = []
        event = self.db.get_event_for_recording(rec_id)
        if event:
            attendees = parse_attendee_names(event.get("attendees"))

        logger.info("Starting transcription job for %s", rec_id)

        worker = TranscribeWorker(session_dir, rec_id, title=title, attendees=attendees)
        worker.transcript_ready.connect(
            lambda result: self._on_worker_transcript_ready(rec_id, result)
        )
        worker.error.connect(lambda error: self._on_worker_error(rec_id, error))
        worker.done.connect(lambda: self._on_worker_done(rec_id))

        self._active_jobs[rec_id] = worker
        self._stashed_workers[rec_id] = worker
        worker.start()
        self.job_started.emit(rec_id)

    def is_running(self, rec_id: str) -> bool:
        """Check if a job is currently running for a recording."""
        return rec_id in self._active_jobs or rec_id in self._stashed_workers

    def cancel(self, rec_id: str):
        """Cancel a running transcription job cooperatively.

        The worker is retained in ``_stashed_workers`` until its unconditional
        ``done`` signal fires, so a thread that is still running after the
        bounded ``wait`` is never destroyed prematurely.
        """
        worker = self._active_jobs.pop(rec_id, None)
        if worker is None:
            worker = self._stashed_workers.get(rec_id)
        if worker is None:
            return

        worker.cancel()
        # Wait briefly for the worker to finish its current bounded call.
        # If it is still running after the timeout, ``done`` will delete it
        # once it finally exits.
        if not worker.wait(3000):
            logger.warning("Transcription worker for %s did not stop within timeout", rec_id)
        logger.info("Cancelled transcription for %s", rec_id)

    def cancel_all(self):
        """Cancel all running transcription jobs."""
        if not self._active_jobs and not self._stashed_workers:
            return

        logger.info("Cancelling all active transcription jobs...")
        for rec_id in set(self._active_jobs) | set(self._stashed_workers):
            self.cancel(rec_id)

    def _on_worker_transcript_ready(self, rec_id: str, json_str: str):
        """Handle worker completion and persist results."""
        self._active_jobs.pop(rec_id, None)

        try:
            # Parse and format for DB
            result = parse_transcription_result(json_str)
        except Exception as e:
            logger.error("Failed to parse transcript for %s: %s", rec_id, e)
            self.db.update_recording_status(rec_id, status="completed")
            self.job_failed.emit(rec_id, f"Failed to parse results: {str(e)}")
            return

        utterances = result.get("utterances", [])
        utterances_json = utterances_to_json(utterances) if utterances else None

        if result.get("partial"):
            # Partial/truncated recovery: save the transcript text and utterances,
            # but do not replace existing action items, mark fully transcribed,
            # emit full completion, compress, or queue File Search.
            existing = self.db.get_transcript(rec_id) or {}
            summary = result.get("summary") or existing.get("summary", "")

            self.db.save_transcript(rec_id, result["transcript"], summary, utterances_json)
            self.db.update_recording_status(rec_id, status="partial")

            logger.info("Partial transcript saved for %s", rec_id)
            self.job_partial.emit(rec_id, json_str)
            return

        if result.get("parse_error"):
            # Complete parse failure: keep the recording as completed but do not
            # overwrite the transcript with raw, unparseable text.
            self.db.update_recording_status(rec_id, status="completed")
            self.job_failed.emit(rec_id, "Transcription result could not be parsed")
            return

        # Full successful transcription
        self.db.save_transcript(
            rec_id, result["transcript"], result["summary"], utterances_json
        )
        self.db.save_action_items(rec_id, result.get("action_items", []))
        self.db.update_recording_status(rec_id, status="transcribed")

        logger.info("Transcription finished and saved for %s", rec_id)
        self.job_finished.emit(rec_id, json_str)

    def _on_worker_error(self, rec_id: str, error_msg: str):
        """Handle worker error."""
        self._active_jobs.pop(rec_id, None)

        logger.error("Transcription failed for %s: %s", rec_id, error_msg)
        self.db.update_recording_status(rec_id, status="completed")
        self.job_failed.emit(rec_id, error_msg)

    def _on_worker_done(self, rec_id: str):
        """Terminal cleanup: delete the worker only after it has truly stopped."""
        worker = self._stashed_workers.pop(rec_id, None)
        self._active_jobs.pop(rec_id, None)
        if worker is not None:
            worker.deleteLater()
