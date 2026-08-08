"""Background worker for AI-enhanced notes generation."""

import json
import logging

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from PyQt6.QtCore import QThread, pyqtSignal

from quinoa.config import config
from quinoa.constants import GEMINI_GENERATION_TIMEOUT_MS, GEMINI_MODEL_TRANSCRIPTION

logger = logging.getLogger("quinoa")


class EnhancedNotesResponse(BaseModel):
    """Structured response for enhanced notes."""

    enhanced_notes: str


class EnhanceWorker(QThread):
    """Background thread for enhancing notes with AI."""

    # ``notes_ready`` and ``error`` carry the job outcome.  ``done`` is emitted
    # unconditionally from ``finally`` and avoids shadowing ``QThread.finished``.
    notes_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, notes: str, transcript: str, summary: str | None = None):
        super().__init__()
        self.notes = notes
        self.transcript = transcript
        self.summary = summary
        self._client: genai.Client | None = None

    def cancel(self) -> None:
        """Cooperatively cancel and close the per-worker HTTP client."""
        self.requestInterruption()
        self._close_client()

    def _close_client(self) -> None:
        """Close the per-worker client if it is safe to do so.

        The client is owned by this worker.  Closing it from any thread while
        a request is in flight will usually abort the blocking call and let
        ``run`` exit.  Errors during close are ignored because the worker is
        already being discarded.
        """
        client = self._client
        if client is None:
            return
        try:
            client.close()
        except Exception:
            pass
        finally:
            self._client = None

    def run(self):
        try:
            api_key = config.get("api_key")
            if not api_key:
                self.error.emit("Gemini API key not configured.")
                return

            if not self.notes.strip():
                self.error.emit("No notes to enhance.")
                return

            if not self.transcript.strip():
                self.error.emit("No transcript available for context.")
                return

            # Bound generation calls with an explicit HTTP timeout.
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=GEMINI_GENERATION_TIMEOUT_MS),
            )

            # Build the prompt
            prompt = self._build_prompt()

            logger.info("Generating enhanced notes...")
            response = self._client.models.generate_content(
                model=config.get("gemini_model") or GEMINI_MODEL_TRANSCRIPTION,
                contents=[types.Content(parts=[types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EnhancedNotesResponse,
                ),
            )

            response_text = response.text or ""
            result = json.loads(response_text)
            enhanced = result.get("enhanced_notes", "")

            if not enhanced:
                self.error.emit("Failed to generate enhanced notes.")
                return

            if self.isInterruptionRequested():
                return

            self.notes_ready.emit(enhanced)

        except (errors.APIError, httpx.HTTPError) as e:
            if not self.isInterruptionRequested():
                logger.exception("API/network error enhancing notes")
                self.error.emit(str(e))
        except Exception as e:
            if not self.isInterruptionRequested():
                logger.exception("Error enhancing notes")
                self.error.emit(str(e))
        finally:
            self._close_client()
            self.done.emit()

    def _build_prompt(self) -> str:
        """Build the prompt for note enhancement."""
        summary_section = ""
        if self.summary:
            summary_section = f"""
## Meeting Summary
{self.summary}
"""

        return f"""You are a meeting assistant helping to enhance and expand meeting notes.

Given the user's original notes and the meeting transcript, create enhanced notes that:
1. Keep the user's original structure and key points
2. Add important details and context from the transcript that the user may have missed
3. Clarify any ambiguous points using transcript context
4. Add any action items or decisions mentioned in the transcript but not in the notes
5. Organize information clearly with headers and bullet points
6. Use markdown formatting

Important guidelines:
- Preserve the user's voice and style
- Don't remove anything the user wrote - only add and clarify
- Focus on actionable and important information
- Keep it concise but comprehensive
- Use ## for main sections, ### for subsections
- Use bullet points for lists
{summary_section}
## User's Original Notes
{self.notes}

## Meeting Transcript
{self.transcript}

Generate enhanced notes in markdown format. Return ONLY the enhanced notes content, properly formatted with markdown."""
