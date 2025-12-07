import logging
import os

from google import genai
from google.genai import types
from pydantic import BaseModel

from quinoa.constants import GEMINI_MODEL_TRANSCRIPTION

logger = logging.getLogger("quinoa")


class ActionItem(BaseModel):
    text: str
    assignee: str | None = None


class Utterance(BaseModel):
    """A single speaker utterance in the transcript."""

    speaker: str  # "Me", "Speaker 2", or detected name
    text: str


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
5. Provide a concise summary of the meeting (2-3 sentences)
6. Extract any action items mentioned

Keep utterances reasonably sized - split long monologues into paragraphs.
"""


class GeminiTranscriber:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found. Please set it in environment variables.")
        self.client = genai.Client(api_key=self.api_key)

    def transcribe(self, audio_path: str, prompt: str | None = None) -> str:
        # Upload file
        logger.info("Uploading %s...", audio_path)
        audio_file = self.client.files.upload(file=audio_path)

        if not audio_file.uri:
            raise ValueError("Failed to get file URI from upload response")

        # Default prompt
        if not prompt:
            prompt = DEFAULT_TRANSCRIPTION_PROMPT

        logger.info("Generating transcript...")
        response = self.client.models.generate_content(
            model=GEMINI_MODEL_TRANSCRIPTION,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_text(text=prompt),
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

        return str(response.text)
