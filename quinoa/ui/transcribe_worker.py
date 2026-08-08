"""Background worker for transcription tasks."""

import logging
import os
import threading

import httpx
from google.genai import errors
from PyQt6.QtCore import QMutex, QThread, pyqtSignal

from quinoa.audio.mixer import MixCancelledError, create_stereo_mix
from quinoa.config import config
from quinoa.transcription.gemini import GeminiTranscriber

logger = logging.getLogger("quinoa")


class TranscribeWorker(QThread):
    """Background thread for audio transcription."""

    # ``transcript_ready`` and ``error`` carry the job outcome.  ``done`` is
    # emitted unconditionally from ``finally`` so managers can safely wait for
    # terminal cleanup without shadowing ``QThread.finished``.
    transcript_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(
        self,
        output_dir: str,
        rec_id: str,
        title: str | None = None,
        attendees: list[str] | None = None,
    ):
        super().__init__()
        self.output_dir = output_dir
        self.rec_id = rec_id
        self.title = title
        self.attendees = attendees or []
        self._is_cancelled = False
        self._mutex = QMutex()
        self._cancel_event = threading.Event()

    def cancel(self):
        """Cooperatively cancel the worker."""
        self._mutex.lock()
        self._is_cancelled = True
        self._cancel_event.set()
        self.requestInterruption()
        self._mutex.unlock()

    def run(self):
        try:
            if self._is_cancelled or self.isInterruptionRequested():
                return

            mic_path = os.path.join(self.output_dir, "microphone.wav")
            sys_path = os.path.join(self.output_dir, "system.wav")
            stereo_path = os.path.join(self.output_dir, "mixed_stereo.wav")

            # 1. Mix audio if stereo doesn't already exist
            if not os.path.exists(stereo_path):
                if os.path.exists(sys_path):
                    if self._is_cancelled or self.isInterruptionRequested():
                        return
                    logger.debug("Mixing audio for transcription: %s", self.rec_id)

                    try:
                        create_stereo_mix(
                            mic_path,
                            sys_path,
                            stereo_path,
                            cancellation_event=self._cancel_event,
                        )
                    except MixCancelledError:
                        logger.info("Stereo mix cancelled for %s", self.rec_id)
                        return

                    if self._is_cancelled or self.isInterruptionRequested():
                        return

                    upload_path = stereo_path
                elif os.path.exists(mic_path):
                    upload_path = mic_path
                else:
                    self.error.emit("Audio files not found.")
                    return
            else:
                upload_path = stereo_path

            if self._is_cancelled or self.isInterruptionRequested():
                return

            # 2. Transcribe
            logger.info("Starting Gemini transcription for %s", self.rec_id)
            api_key = config.get("api_key")
            transcriber = GeminiTranscriber(api_key=api_key)

            # The transcribe call is network bound and blocks, but it is bounded
            # by HttpOptions timeouts and checks the cancellation event.
            transcript = transcriber.transcribe(
                upload_path,
                title=self.title,
                attendees=self.attendees,
                cancellation_event=self._cancel_event,
            )

            if self._is_cancelled or self.isInterruptionRequested():
                return

            self.transcript_ready.emit(transcript)

        except (errors.APIError, httpx.HTTPError) as e:
            if not self._is_cancelled:
                logger.exception("TranscribeWorker API/network error for %s", self.rec_id)
                self.error.emit(str(e))
        except Exception as e:
            if not self._is_cancelled:
                logger.exception("TranscribeWorker error for %s", self.rec_id)
                self.error.emit(str(e))
        finally:
            # Always emit a terminal signal so the manager can delete the
            # worker once it truly stops, even after a cancel timeout.
            self.done.emit()
