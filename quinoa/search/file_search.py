"""Gemini File Search API wrapper."""

import logging
import tempfile
import time
from typing import Any

from google import genai
from google.genai import types

from quinoa.config import config
from quinoa.constants import GEMINI_MODEL_SEARCH

logger = logging.getLogger("quinoa")


class FileSearchError(Exception):
    """Base exception for File Search operations."""

    pass


class FileSearchManager:
    """Manages Gemini File Search store and file operations."""

    STORE_DISPLAY_NAME = "quinoa-meetings"

    def __init__(self, api_key: str, store_name: str | None = None):
        """Initialize the File Search manager.

        Args:
            api_key: Gemini API key
            store_name: Existing store name (if any)
        """
        self.client = genai.Client(api_key=api_key)
        self._store_name = store_name

    @property
    def store_name(self) -> str | None:
        """Get the current store name."""
        return self._store_name

    def ensure_store_exists(self) -> str:
        """Create or retrieve the File Search store.

        Returns the store name identifier.
        """
        if self._store_name:
            # Verify existing store is valid
            try:
                self.client.file_search_stores.get(name=self._store_name)
                logger.debug("Using existing File Search store: %s", self._store_name)
                return self._store_name
            except Exception:
                logger.warning("Stored File Search store not found, creating new one")
                self._store_name = None

        # Create new store
        try:
            store = self.client.file_search_stores.create(
                config={"display_name": self.STORE_DISPLAY_NAME}
            )
            self._store_name = store.name
            logger.info("Created File Search store: %s", self._store_name)
            if self._store_name is None:
                raise FileSearchError("Store created but has no name")
            return self._store_name
        except Exception as e:
            raise FileSearchError(f"Failed to create File Search store: {e}") from e

    def upload_meeting(
        self,
        rec_id: str,
        content: str,
        meeting_date: str,
    ) -> str:
        """Upload meeting content to File Search store.

        Args:
            rec_id: Recording ID
            content: Formatted meeting content (markdown)
            meeting_date: Meeting date string for metadata

        Returns:
            The Gemini document resource name for tracking and deletion.
        """
        if not self._store_name:
            raise FileSearchError("Store not initialized. Call ensure_store_exists() first.")

        display_name = f"meeting_{rec_id}.md"

        try:
            # Write content to a temporary file for upload
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name

            # Upload file and import into store
            operation = self.client.file_search_stores.upload_to_file_search_store(
                file=tmp_path,
                file_search_store_name=self._store_name,
                config={
                    "display_name": display_name,
                    "custom_metadata": [
                        {"key": "recording_id", "string_value": rec_id},
                        {"key": "meeting_date", "string_value": meeting_date},
                    ],
                },
            )

            # Wait for import to complete
            while not operation.done:
                time.sleep(2)
                operation = self.client.operations.get(operation)

            # Extract document resource name for future deletion
            document_name = ""
            if operation.response:
                document_name = operation.response.document_name or ""

            logger.info("Uploaded meeting %s to File Search (document: %s)", rec_id, document_name)
            return document_name or display_name

        except Exception as e:
            raise FileSearchError(f"Failed to upload meeting {rec_id}: {e}") from e

    def delete_meeting(self, document_name: str) -> bool:
        """Remove a meeting document from the File Search store.

        Args:
            document_name: The Gemini document resource name
                (e.g. 'fileSearchStores/.../documents/...').

        Returns:
            True if successful (or deletion not needed/skipped).
        """
        if not document_name:
            return True

        # Legacy entries may store display names (e.g. 'meeting_rec_xxx.md')
        # instead of resource paths. These can't be deleted via the API.
        if "/" not in document_name:
            logger.debug(
                "Skipping deletion for legacy display name '%s' (not a resource path)",
                document_name,
            )
            return True

        try:
            self.client.file_search_stores.documents.delete(name=document_name)
            logger.info("Deleted document %s from File Search", document_name)
            return True
        except Exception as e:
            logger.warning("Failed to delete document %s: %s", document_name, e)
            return False

    def query(
        self,
        question: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Query the File Search store with optional chat context.

        Args:
            question: User's question
            chat_history: Previous messages in the conversation

        Returns:
            Tuple of (response_text, citations).
        """
        if not self._store_name:
            raise FileSearchError("Store not initialized. Call ensure_store_exists() first.")

        # Build conversation context
        contents = []
        if chat_history:
            for msg in chat_history[-10:]:  # Last 10 messages for context
                contents.append(
                    types.Content(
                        role=msg["role"], parts=[types.Part.from_text(text=msg["content"])]
                    )
                )

        # Add current question
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))

        # System instruction for search-focused assistant
        system_instruction = """You are a helpful assistant for searching through meeting recordings and notes.
Your primary purpose is to help users find information from their past meetings.
When answering:
- Be concise and direct
- Cite specific meetings when referencing information
- If you can't find relevant information in the meetings, say so clearly
- Focus on facts from the meetings, not general knowledge
- When quoting, use the exact text from the transcript"""

        try:
            logger.debug("File Search query: %s", question)
            logger.debug("Chat history length: %d", len(chat_history) if chat_history else 0)
            logger.debug("Using store: %s", self._store_name)

            # Use configured model, but fall back to GEMINI_MODEL_SEARCH if the
            # configured model doesn't support tool use (file_search requires it).
            model = config.get("gemini_model") or GEMINI_MODEL_SEARCH

            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        tools=[
                            types.Tool(
                                file_search=types.FileSearch(
                                    file_search_store_names=[self._store_name]
                                )
                            )
                        ],
                    ),
                )
            except Exception as e:
                # If the configured model doesn't support tools, retry with the
                # known-good default search model
                if model != GEMINI_MODEL_SEARCH and "tool" in str(e).lower():
                    logger.warning(
                        "Model %s doesn't support tools, falling back to %s",
                        model,
                        GEMINI_MODEL_SEARCH,
                    )
                    response = self.client.models.generate_content(
                        model=GEMINI_MODEL_SEARCH,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            tools=[
                                types.Tool(
                                    file_search=types.FileSearch(
                                        file_search_store_names=[self._store_name]
                                    )
                                )
                            ],
                        ),
                    )
                else:
                    raise

            # Log raw response structure for debugging
            logger.debug(
                "Response candidates: %d", len(response.candidates) if response.candidates else 0
            )

            # Extract citations from grounding metadata
            citations = []
            if response.candidates and response.candidates[0].grounding_metadata:
                metadata = response.candidates[0].grounding_metadata
                logger.debug("Grounding metadata: %s", metadata)

                # Extract citation info if available
                if hasattr(metadata, "grounding_chunks") and metadata.grounding_chunks:
                    grounding_chunks = metadata.grounding_chunks
                    logger.debug("Grounding chunks: %d", len(grounding_chunks))
                    for i, chunk in enumerate(grounding_chunks):
                        logger.debug("Chunk %d: %s", i, chunk)
                        if hasattr(chunk, "retrieved_context"):
                            ctx = chunk.retrieved_context
                            citation = {
                                "title": getattr(ctx, "title", "Unknown"),
                                "uri": getattr(ctx, "uri", ""),
                            }
                            citations.append(citation)
                            logger.debug("Citation %d: %s", i, citation)
                else:
                    logger.debug("No grounding_chunks attribute found")
            else:
                logger.debug("No grounding metadata in response")

            logger.info(
                "File Search response: %d chars, %d citations",
                len(response.text or ""),
                len(citations),
            )

            return response.text or "", citations

        except Exception as e:
            logger.exception("File Search query failed")
            raise FileSearchError(f"Query failed: {e}") from e
