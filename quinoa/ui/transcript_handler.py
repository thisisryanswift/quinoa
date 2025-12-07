"""Shared transcript result handling utilities."""

import json
import logging

logger = logging.getLogger("quinoa")


def parse_transcription_result(json_str: str) -> dict:
    """Parse transcription JSON result.

    Returns dict with keys: utterances, summary, action_items, transcript (plain text), parse_error
    """
    # Strip markdown code fences if present (Gemini sometimes wraps JSON)
    cleaned = json_str.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

    try:
        data = json.loads(cleaned)

        # Get utterances (new format)
        utterances = data.get("utterances", [])

        # Preserve original speaker labels for each utterance
        for u in utterances:
            if "original_speaker" not in u:
                u["original_speaker"] = u.get("speaker", "Unknown")

        # Build plain text transcript from utterances for backwards compatibility
        if utterances:
            transcript_lines = []
            for u in utterances:
                speaker = u.get("speaker", "Unknown")
                text = u.get("text", "")
                transcript_lines.append(f"{speaker}: {text}")
            transcript = "\n\n".join(transcript_lines)
        else:
            # Fallback to old format
            transcript = data.get("transcript", "")

        return {
            "utterances": utterances,
            "transcript": transcript,
            "summary": data.get("summary", ""),
            "action_items": data.get("action_items", []),
            "parse_error": False,
        }
    except json.JSONDecodeError:
        return {
            "utterances": [],
            "transcript": json_str,
            "summary": "",
            "action_items": [],
            "parse_error": True,
        }


def format_transcript_display(transcript: str, summary: str) -> str:
    """Format transcript and summary for display (plain text fallback)."""
    if summary:
        return f"## Summary\n{summary}\n\n## Transcript\n{transcript}"
    return transcript


def utterances_to_json(utterances: list[dict]) -> str:
    """Convert utterances list to JSON string for storage."""
    return json.dumps(utterances)


def utterances_from_json(json_str: str | None) -> list[dict]:
    """Parse utterances JSON from storage."""
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return []


def apply_speaker_names(utterances: list[dict], speaker_names: dict[str, str]) -> list[dict]:
    """Apply speaker name mappings to utterances."""
    result = []
    for u in utterances:
        new_u = u.copy()
        original_speaker = u.get("speaker", "Unknown")
        new_u["display_speaker"] = speaker_names.get(original_speaker, original_speaker)
        result.append(new_u)
    return result


def format_action_item(action: dict) -> str:
    """Format a single action item for display."""
    label = str(action.get("text", ""))
    assignee = action.get("assignee")
    if assignee:
        label += f" ({assignee})"
    return label
