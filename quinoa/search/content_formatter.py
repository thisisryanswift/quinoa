"""Format meeting data for File Search upload."""

import hashlib
from datetime import datetime
from typing import Any


def format_meeting_document(
    recording: dict[str, Any],
    transcript: dict[str, Any] | None,
    notes: str,
    action_items: list[dict[str, Any]],
    folder_name: str | None = None,
    attendees: list[dict[str, Any]] | None = None,
) -> str:
    """Format meeting data as structured markdown for File Search.

    Uses markdown for optimal chunking and retrieval quality.
    """
    sections = []

    # Title and metadata
    title = recording.get("title", "Untitled Meeting")
    sections.append(f"# {title}")

    # Parse and format datetime
    started_at = recording.get("started_at")
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at) if isinstance(started_at, str) else started_at
            date_str = dt.strftime("%B %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            date_str = str(started_at)
    else:
        date_str = "Unknown date"

    # Format duration
    duration = recording.get("duration_seconds", 0)
    if duration:
        mins = int(duration // 60)
        secs = int(duration % 60)
        duration_str = f"{mins}:{secs:02d}"
    else:
        duration_str = "Unknown duration"

    sections.append(f"{date_str} ({duration_str})")

    # Metadata line: folder and attendees
    meta_parts = []
    if folder_name:
        meta_parts.append(f"Series: {folder_name}")
    if attendees:
        names = [a.get("name") or a.get("email", "Unknown") for a in attendees]
        meta_parts.append(f"Attendees: {', '.join(names)}")
    if meta_parts:
        sections.append(" | ".join(meta_parts))

    sections.append("")

    # Notes section
    if notes and notes.strip():
        sections.append("## Notes")
        sections.append(notes.strip())
        sections.append("")

    # Summary section
    if transcript and transcript.get("summary"):
        sections.append("## Summary")
        sections.append(transcript["summary"])
        sections.append("")

    # Action items section
    if action_items:
        sections.append("## Action Items")
        for item in action_items:
            assignee = item.get("assignee") or "Unassigned"
            status = "x" if item.get("status") == "completed" else " "
            sections.append(f"- [{status}] {item['text']} (Assignee: {assignee})")
        sections.append("")

    # Transcript section
    if transcript and transcript.get("text"):
        sections.append("## Transcript")
        sections.append(transcript["text"])

    return "\n".join(sections)


def compute_content_hash(content: str) -> str:
    """Compute SHA256 hash for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()
