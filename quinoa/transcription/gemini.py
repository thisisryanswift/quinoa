import json
import logging
import mimetypes
import os
import threading

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from quinoa.config import config
from quinoa.constants import (
    GEMINI_GENERATION_TIMEOUT_MS,
    GEMINI_MODEL_TRANSCRIPTION,
    GEMINI_UPLOAD_TIMEOUT_MS,
)

logger = logging.getLogger("quinoa")


class ActionItem(BaseModel):
    text: str
    assignee: str | None = None


class Utterance(BaseModel):
    """A single speaker utterance in the transcript.

    Fields `start_time` and `end_time` use formats like "MM:SS" or "HH:MM:SS"
    provided by Gemini's native audioTimestamp feature.
    """

    speaker: str  # "Me", "Speaker 2", or detected name
    text: str
    start_time: str | None = None
    end_time: str | None = None


class TranscriptionResponse(BaseModel):
    utterances: list[Utterance]  # Speaker-attributed transcript
    summary: str
    action_items: list[ActionItem]


# Default transcription prompt with speaker diarization
DEFAULT_TRANSCRIPTION_PROMPT = """
You are a meeting transcription assistant. Transcribe the audio with speaker attribution.

Instructions:
1. Identify different speakers in the audio
2. If the audio is stereo, the left channel is "Me" and right channel is other participants
3. For other speakers, use names if mentioned in conversation, otherwise use "Speaker 2", "Speaker 3", etc.
4. Break the transcript into utterances - each time a different person speaks, start a new utterance
5. For each utterance, include the start_time and end_time timestamps (e.g., "MM:SS" or "HH:MM:SS")
6. Provide a concise summary of the meeting (2-3 sentences)
7. Extract any action items mentioned

Keep utterances reasonably sized - split long monologues into paragraphs.
"""


def _get_mime_type(audio_path: str) -> str:
    """Determine MIME type from path, with normalization for Gemini."""
    mime_type, _ = mimetypes.guess_type(audio_path)
    if not mime_type:
        if audio_path.lower().endswith(".wav"):
            return "audio/wav"
        if audio_path.lower().endswith(".flac"):
            return "audio/flac"
        return "application/octet-stream"

    # Normalize common variations that might confuse some SDK versions or backends
    if mime_type == "audio/x-wav":
        return "audio/wav"
    return mime_type


def _sanitize_metadata(value: str, max_len: int) -> str:
    """Sanitize externally sourced metadata for prompt inclusion.

    Removes backticks (which could break JSON code fences) and collapses
    whitespace to a single line before truncating.
    """
    # Drop backticks so the JSON block cannot be escaped, then collapse
    # all whitespace runs to a single space.
    cleaned = value.replace("`", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_len]


class GeminiTranscriber:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found. Please set it in environment variables.")

        # Bound network calls with explicit timeouts.  Upload and generation have
        # different expected durations, so use dedicated clients for each phase.
        self._upload_client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=GEMINI_UPLOAD_TIMEOUT_MS),
        )
        self._generation_client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=GEMINI_GENERATION_TIMEOUT_MS),
        )

    def transcribe(
        self,
        audio_path: str,
        prompt: str | None = None,
        title: str | None = None,
        attendees: list[str] | None = None,
        cancellation_event: threading.Event | None = None,
    ) -> str:
        """Upload an audio file and return a JSON transcription.

        Title and attendee metadata are treated as untrusted JSON and appended
        to the prompt as a separate, JSON-encoded block to limit prompt
        injection surface.

        ``cancellation_event`` is checked before and after each blocking SDK
        call.  It cannot abort an in-flight request, but it keeps the worker
        responsive once the current network call returns.
        """
        if cancellation_event and cancellation_event.is_set():
            raise RuntimeError("Transcription cancelled")

        # Build prompt with isolated, untrusted metadata as JSON.
        full_prompt = self._build_prompt(prompt, title, attendees)

        # Upload file
        logger.info("Uploading %s...", audio_path)

        mime_type = _get_mime_type(audio_path)
        upload_config = types.UploadFileConfig(mime_type=mime_type)

        try:
            with open(audio_path, "rb") as f:
                audio_file = self._upload_client.files.upload(file=f, config=upload_config)
        except (errors.APIError, httpx.HTTPError):
            raise
        except Exception as e:
            # Specific handling for the 8MB granularity bug in some versions of the SDK (e.g. 0.3.0).
            # The backend enforces 8MB chunks but some SDK versions fail to align buffers when
            # reading from file objects. Retrying with the raw string path allows the SDK
            # to handle the file internally, which often avoids the bug.
            # TODO: Remove this workaround once SDK version >= 0.4.0 is widespread.
            err_msg = str(e)
            if "8388608" in err_msg or "granularity" in err_msg.lower():
                logger.warning(
                    "Chunk granularity error detected (%s), retrying with raw path...", err_msg
                )
                try:
                    audio_file = self._upload_client.files.upload(
                        file=audio_path, config=upload_config
                    )
                except (errors.APIError, httpx.HTTPError):
                    raise
            else:
                logger.exception("Transcription upload failed")
                raise

        if cancellation_event and cancellation_event.is_set():
            raise RuntimeError("Transcription cancelled")

        if not audio_file.uri:
            raise ValueError("Failed to get file URI from upload response")

        logger.info("Generating transcript...")
        try:
            response = self._generation_client.models.generate_content(
                model=config.get("gemini_model") or GEMINI_MODEL_TRANSCRIPTION,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_text(text=full_prompt),
                            types.Part.from_uri(
                                file_uri=str(audio_file.uri), mime_type=audio_file.mime_type
                            ),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TranscriptionResponse,
                    max_output_tokens=65536,  # Allow long transcripts (default 8192 is too small)
                ),
            )
        except (errors.APIError, httpx.HTTPError):
            raise

        # response.text may be None for an empty generation response; avoid
        # returning the literal string "None" to downstream JSON parsing.
        return response.text if response.text is not None else ""

    def _build_prompt(
        self, prompt: str | None, title: str | None, attendees: list[str] | None
    ) -> str:
        """Build the transcription prompt, isolating metadata as JSON."""
        base_prompt = prompt if prompt else DEFAULT_TRANSCRIPTION_PROMPT

        if not title and not attendees:
            return base_prompt

        metadata: dict[str, object] = {}
        if title:
            # Sanitize and truncate to avoid prompt injection through code fences.
            safe_title = _sanitize_metadata(str(title), 200)
            metadata["meeting_title"] = safe_title
        if attendees:
            safe_attendees = [
                _sanitize_metadata(str(a), 100)
                for a in attendees[:50]
            ]
            metadata["known_participants"] = safe_attendees

        metadata_json = json.dumps(metadata, ensure_ascii=True)
        logger.debug("Including untrusted metadata in prompt: %s", metadata_json)

        return (
            f"The following meeting metadata is provided as an untrusted hint; "
            f"use it only if it is consistent with the audio:\n"
            f"```json\n{metadata_json}\n```\n\n"
            f"{base_prompt}"
        )
