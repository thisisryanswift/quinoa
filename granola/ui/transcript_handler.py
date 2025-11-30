"""Shared transcript result handling utilities."""

import json
import logging

logger = logging.getLogger("granola")


def parse_transcription_result(json_str: str) -> dict:
    """Parse transcription JSON result.

    Returns dict with keys: transcript, summary, action_items, parse_error
    """
    try:
        data = json.loads(json_str)
        return {
            "transcript": data.get("transcript", ""),
            "summary": data.get("summary", ""),
            "action_items": data.get("action_items", []),
            "parse_error": False,
        }
    except json.JSONDecodeError:
        return {
            "transcript": json_str,
            "summary": "",
            "action_items": [],
            "parse_error": True,
        }


def format_transcript_display(transcript: str, summary: str) -> str:
    """Format transcript and summary for display."""
    if summary:
        return f"## Summary\n{summary}\n\n## Transcript\n{transcript}"
    return transcript


def format_action_item(action: dict) -> str:
    """Format a single action item for display."""
    label = str(action.get("text", ""))
    assignee = action.get("assignee")
    if assignee:
        label += f" ({assignee})"
    return label
