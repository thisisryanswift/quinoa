import json


def parse_attendee_names(attendees_json: str | None) -> list[str]:
    """Parse attendee names from a JSON string from the calendar.

    Handles structured dicts, bare strings, and malformed data robustly.
    Returns a list of names or emails.
    """
    if not attendees_json:
        return []

    try:
        attendee_list = json.loads(attendees_json)
        if not isinstance(attendee_list, list):
            return []

        names = []
        for a in attendee_list:
            if isinstance(a, dict):
                # Use name if present, fallback to email, then 'Unknown'
                name = a.get("name") or a.get("email") or "Unknown"
                names.append(name)
            elif isinstance(a, str):
                # Handle bare string emails/names
                names.append(a)
        return names
    except (json.JSONDecodeError, TypeError):
        return []
