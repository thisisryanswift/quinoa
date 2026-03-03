"""Shared transcript result handling utilities."""

import json
import logging
import re

logger = logging.getLogger("quinoa")

# Regex for a JSON string value (robustly handles escaped quotes and backslashes)
# This matches a quote, then any sequence of (non-quote-non-backslash OR backslash-followed-by-anything)
_JSON_STR_PATTERN = r'"((?:[^"\\]|\\.)*)"'

# Pre-compiled regexes for robust utterance extraction from malformed/truncated JSON
# Note: These use [^{}]*? which means they will skip any utterance containing literal braces { }
_OBJ_PATTERN = re.compile(r"\{[^{}]*?\"speaker\"[^{}]*?\}", re.DOTALL)
_SPEAKER_RE = re.compile(r"\"speaker\"\s*:\s*" + _JSON_STR_PATTERN)
_TEXT_RE = re.compile(r"\"text\"\s*:\s*" + _JSON_STR_PATTERN)
_START_TIME_RE = re.compile(r"\"start_time\"\s*:\s*" + _JSON_STR_PATTERN)
_END_TIME_RE = re.compile(r"\"end_time\"\s*:\s*" + _JSON_STR_PATTERN)


def _unescape_json_string(s: str) -> str:
    """Robustly unescape a JSON string value.

    Uses json.loads for standard unescaping, with a manual fallback for partial/invalid sequences.
    """
    try:
        return str(json.loads(f'"{s}"'))
    except (json.JSONDecodeError, ValueError):
        # Manual fallback for edge cases
        return s.replace("\\\\", "\\").replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")


def _extract_utterances_from_truncated(json_str: str) -> list[dict]:
    """Extract utterances from potentially truncated JSON using regex.

    Handles cases where Gemini cuts off mid-response or includes extra fields.

    LIMITATION: Utterances containing literal braces { or } in the text will be
    skipped by the current regex implementation.
    """
    utterances = []

    for match in _OBJ_PATTERN.finditer(json_str):
        obj_text = match.group(0)

        # Extract fields using individual regexes (robust to field order and extra fields)
        speaker_match = _SPEAKER_RE.search(obj_text)
        text_match = _TEXT_RE.search(obj_text)
        start_match = _START_TIME_RE.search(obj_text)
        end_match = _END_TIME_RE.search(obj_text)

        if speaker_match and text_match:
            speaker = _unescape_json_string(speaker_match.group(1))
            text = _unescape_json_string(text_match.group(1))

            utterance = {
                "speaker": speaker,
                "text": text,
                "original_speaker": speaker,
            }

            if start_match:
                utterance["start_time"] = _unescape_json_string(start_match.group(1))
            if end_match:
                utterance["end_time"] = _unescape_json_string(end_match.group(1))

            utterances.append(utterance)

    if utterances:
        logger.info("Regex recovery found %d utterances", len(utterances))
    else:
        logger.warning(
            "Regex recovery failed to find any utterances in input of length %d", len(json_str)
        )

    return utterances


def _build_plain_transcript(utterances: list[dict]) -> str:
    """Build a plain text transcript from utterances.

    Includes start_time if present for better context in AI enhancement.
    We omit end_time for brevity in the plain text representation.
    """
    transcript_lines = []
    for u in utterances:
        speaker = u.get("speaker", "Unknown")
        text = u.get("text", "")
        start_time = u.get("start_time")

        line = f"[{start_time}] {speaker}: {text}" if start_time else f"{speaker}: {text}"
        transcript_lines.append(line)

    return "\n\n".join(transcript_lines)


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

        if isinstance(data, list):
            # Top-level is a list of utterances.
            # Filter for dictionaries with a 'speaker' key.
            utterances = [u for u in data if isinstance(u, dict) and "speaker" in u]
            summary = ""
            action_items = []

        else:
            # Get utterances (new format)
            utterances = data.get("utterances", [])
            summary = data.get("summary", "")
            action_items = data.get("action_items", [])

        # Preserve original speaker labels for each utterance
        for u in utterances:
            if "original_speaker" not in u:
                u["original_speaker"] = u.get("speaker", "Unknown")

        # Build plain text transcript from utterances for backwards compatibility
        if utterances:
            transcript = _build_plain_transcript(utterances)
        elif isinstance(data, dict):
            # Fallback to old format
            transcript = data.get("transcript", "")
        else:
            transcript = ""

        return {
            "utterances": utterances,
            "transcript": transcript,
            "summary": summary,
            "action_items": action_items,
            "parse_error": False,
        }
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed at position %s: %s. Attempting recovery...", e.pos, e.msg)

        # Try to extract utterances from truncated JSON
        utterances = _extract_utterances_from_truncated(cleaned)

        if utterances:
            logger.info("Recovered %d utterances from truncated response", len(utterances))
            transcript = _build_plain_transcript(utterances)

            return {
                "utterances": utterances,
                "transcript": transcript,
                "summary": "",  # Can't recover summary from truncated response
                "action_items": [],  # Can't recover action items
                "parse_error": False,  # We recovered useful data
            }

        # Complete failure - return raw text
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
        result: list[dict] = json.loads(json_str)
        return result
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
