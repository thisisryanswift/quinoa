from datetime import datetime
from unittest.mock import MagicMock

from quinoa.calendar.client import CalendarClient


def test_fetch_calendar_events_normalizes_new_york_bounds_to_utc() -> None:
    request = MagicMock()
    request.execute.return_value = {"items": []}
    events = MagicMock()
    events.list.return_value = request
    client = CalendarClient.__new__(CalendarClient)
    client.service = MagicMock()
    client.service.events.return_value = events

    client._fetch_calendar_events(
        "primary",
        datetime(2026, 8, 8, 0, 0),
        datetime(2026, 8, 9, 0, 0),
        video_only=False,
    )

    kwargs = events.list.call_args.kwargs
    assert kwargs["timeMin"] == "2026-08-08T04:00:00+00:00"
    assert kwargs["timeMax"] == "2026-08-09T04:00:00+00:00"
