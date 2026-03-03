"""Background worker for transcription tasks."""

import logging
import os
import subprocess

from PyQt6.QtCore import QMutex, QThread, pyqtSignal

from quinoa.audio.mixer import MIX_FILTER_COMPLEX
from quinoa.config import config
from quinoa.transcription.gemini import DEFAULT_TRANSCRIPTION_PROMPT, GeminiTranscriber

logger = logging.getLogger("quinoa")


class TranscribeWorker(QThread):
    """Background thread for audio transcription."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

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
        self._process: subprocess.Popen | None = None

    def cancel(self):
        """Cooperatively cancel the worker."""
        self._mutex.lock()
        self._is_cancelled = True
        if self._process:
            try:
                self._process.kill()
                logger.info("Killed ffmpeg process for %s", self.rec_id)
            except Exception:
                pass
        self._mutex.unlock()

    def run(self):
        try:
            if self._is_cancelled:
                return

            mic_path = os.path.join(self.output_dir, "microphone.wav")
            sys_path = os.path.join(self.output_dir, "system.wav")
            stereo_path = os.path.join(self.output_dir, "mixed_stereo.wav")

            # 1. Mix audio if stereo doesn't already exist
            if not os.path.exists(stereo_path):
                if os.path.exists(sys_path):
                    if self._is_cancelled:
                        return
                    logger.debug("Mixing audio for transcription: %s", self.rec_id)

                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        mic_path,
                        "-i",
                        sys_path,
                        "-filter_complex",
                        MIX_FILTER_COMPLEX,
                        "-map",
                        "[a]",
                        stereo_path,
                    ]

                    self._mutex.lock()
                    if self._is_cancelled:
                        self._mutex.unlock()
                        return
                    self._process = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    self._mutex.unlock()

                    _, stderr = self._process.communicate()

                    self._mutex.lock()
                    returncode = self._process.returncode if self._process else -1

                    self._process = None
                    if self._is_cancelled:
                        self._mutex.unlock()
                        return
                    self._mutex.unlock()

                    if returncode != 0:
                        self.error.emit(f"Mixing failed: {stderr.decode()}")
                        return

                    upload_path = stereo_path
                elif os.path.exists(mic_path):
                    upload_path = mic_path
                else:
                    self.error.emit("Audio files not found.")
                    return
            else:
                upload_path = stereo_path

            if self._is_cancelled:
                return

            # 2. Transcribe
            logger.info("Starting Gemini transcription for %s", self.rec_id)
            api_key = config.get("api_key")
            transcriber = GeminiTranscriber(api_key=api_key)

            # Build customized prompt with meeting metadata hints
            # Note: We perform basic sanitization on externally sourced metadata
            # to prevent prompt injection, although risk is mitigated by structured output.
            prompt = None
            if self.title or self.attendees:
                context_hints = []
                if self.title:
                    # Strip newlines and truncate to avoid massive injection
                    safe_title = self.title.replace("\n", " ").strip()[:200]
                    context_hints.append(f"Meeting Title: {safe_title}")
                if self.attendees:
                    # Sanitize and truncate attendee list
                    safe_attendees = [a.replace("\n", " ").strip()[:100] for a in self.attendees]
                    context_hints.append(f"Known Participants: {', '.join(safe_attendees[:50])}")

                hint_text = "\n".join(context_hints)
                prompt = f"Context for this meeting:\n{hint_text}\n\n{DEFAULT_TRANSCRIPTION_PROMPT}"
                logger.debug("Using customized prompt with metadata hints for %s", self.rec_id)

            # The transcribe call is network bound and blocks.
            transcript = transcriber.transcribe(upload_path, prompt=prompt)

            if self._is_cancelled:
                return

            self.finished.emit(transcript)

        except Exception as e:
            if not self._is_cancelled:
                logger.exception("TranscribeWorker error for %s", self.rec_id)
                self.error.emit(str(e))
        finally:
            self._mutex.lock()
            self._process = None
            self._mutex.unlock()
