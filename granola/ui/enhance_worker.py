"""Background worker for AI-enhanced notes generation."""

import logging

from google import genai
from google.genai import types
from pydantic import BaseModel
from PyQt6.QtCore import QThread, pyqtSignal

from granola.config import config

logger = logging.getLogger("granola")


class EnhancedNotesResponse(BaseModel):
    """Structured response for enhanced notes."""

    enhanced_notes: str


class EnhanceWorker(QThread):
    """Background thread for enhancing notes with AI."""

    finished = pyqtSignal(str)  # Enhanced notes markdown
    error = pyqtSignal(str)

    def __init__(self, notes: str, transcript: str, summary: str | None = None):
        super().__init__()
        self.notes = notes
        self.transcript = transcript
        self.summary = summary

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

            client = genai.Client(api_key=api_key)

            # Build the prompt
            prompt = self._build_prompt()

            logger.info("Generating enhanced notes...")
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[types.Content(parts=[types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EnhancedNotesResponse,
                ),
            )

            # Parse the response
            import json

            result = json.loads(response.text)
            enhanced = result.get("enhanced_notes", "")

            if not enhanced:
                self.error.emit("Failed to generate enhanced notes.")
                return

            self.finished.emit(enhanced)

        except Exception as e:
            logger.exception("Error enhancing notes")
            self.error.emit(str(e))

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
