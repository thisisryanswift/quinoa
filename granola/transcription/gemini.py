import logging
import os

from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger("granola")


class ActionItem(BaseModel):
    text: str
    assignee: str | None = None


class TranscriptionResponse(BaseModel):
    transcript: str
    summary: str
    action_items: list[ActionItem]


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
            prompt = """
            You are a meeting assistant. Transcribe the audio and extract action items.
            The audio is stereo: Left=Me, Right=Others.
            """

        logger.info("Generating transcript...")
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
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
            ),
        )

        return str(response.text)
