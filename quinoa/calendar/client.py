"""Google Calendar API client."""

import json
import logging
import re
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger("quinoa")

# Regex patterns for video meeting links
MEET_PATTERN = re.compile(r"https://meet\.google\.com/[a-z]+-[a-z]+-[a-z]+", re.IGNORECASE)
ZOOM_PATTERN = re.compile(r"https://[a-z0-9.-]*zoom\.us/j/\d+", re.IGNORECASE)
TEAMS_PATTERN = re.compile(r"https://teams\.microsoft\.com/l/meetup-join/[^\s]+", re.IGNORECASE)


class CalendarClient:
    """Google Calendar API wrapper."""

    def __init__(self, credentials: Credentials):
        """Initialize the client with valid credentials."""
        self.service = build("calendar", "v3", credentials=credentials)

    def get_todays_events(
        self, calendar_ids: list[str] | None = None, video_only: bool = True
    ) -> list[dict]:
        """Get today's events from specified calendars.

        Args:
            calendar_ids: List of calendar IDs to query. Defaults to ["primary"].
            video_only: If True, only return events with video meeting links.

        Returns:
            List of parsed event dicts.
        """
        if not calendar_ids:
            calendar_ids = ["primary"]

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        return self.get_events(calendar_ids, today, tomorrow, video_only=video_only)

    def get_events(
        self,
        calendar_ids: list[str],
        start_time: datetime,
        end_time: datetime,
        video_only: bool = True,
    ) -> list[dict]:
        """Get events from specified calendars in a time range.

        Args:
            calendar_ids: List of calendar IDs to query.
            start_time: Start of time range.
            end_time: End of time range.
            video_only: If True, only return events with video meeting links.

        Returns:
            List of parsed event dicts.
        """
        all_events = []

        for cal_id in calendar_ids:
            try:
                events = self._fetch_calendar_events(cal_id, start_time, end_time, video_only)
                all_events.extend(events)
            except Exception as e:
                logger.error("Failed to fetch events from calendar %s: %s", cal_id, e)

        # Sort by start time
        all_events.sort(key=lambda e: e["start_time"])

        return all_events

    def _fetch_calendar_events(
        self,
        calendar_id: str,
        start_time: datetime,
        end_time: datetime,
        video_only: bool = True,
    ) -> list[dict]:
        """Fetch events from a single calendar."""
        local_tz = datetime.now().astimezone().tzinfo
        start_aware = start_time.replace(tzinfo=local_tz)
        end_aware = end_time.replace(tzinfo=local_tz)

        result = (
            self.service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_aware.isoformat(),
                timeMax=end_aware.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = []
        for event in result.get("items", []):
            parsed = self._parse_event(event, calendar_id)
            if parsed:
                has_video = bool(parsed.get("meet_link"))
                if has_video or not video_only:
                    events.append(parsed)

        return events

    def _parse_event(self, event: dict, calendar_id: str) -> dict | None:
        """Parse a Google Calendar event into our format.

        Returns None for all-day events (which have 'date' instead of 'dateTime').
        """
        start = event.get("start", {})
        end = event.get("end", {})

        if "dateTime" not in start:
            return None

        meet_link = self._extract_meet_link(event)
        start_time = self._parse_datetime(start.get("dateTime"))
        end_time = self._parse_datetime(end.get("dateTime"))

        if not start_time or not end_time:
            return None

        attendees = self._parse_attendees(event.get("attendees", []))

        return {
            "event_id": event["id"],
            "calendar_id": calendar_id,
            "title": event.get("summary", "Untitled Meeting"),
            "start_time": start_time,
            "end_time": end_time,
            "meet_link": meet_link,
            "attendees": json.dumps(attendees) if attendees else None,
            "organizer_email": event.get("organizer", {}).get("email"),
            "etag": event.get("etag"),
            "recurring_event_id": event.get("recurringEventId"),
        }

    def _extract_meet_link(self, event: dict) -> str | None:
        """Extract video meeting link from event.

        Checks conferenceData first (for native Meet), then falls back
        to searching description and location for Zoom/Teams links.
        """
        # Check native Google Meet in conferenceData
        conference_data = event.get("conferenceData", {})
        for entry_point in conference_data.get("entryPoints", []):
            if entry_point.get("entryPointType") == "video":
                return entry_point.get("uri")

        # Check hangoutLink (older format)
        if event.get("hangoutLink"):
            return event["hangoutLink"]

        # Search description and location for video links
        text_to_search = event.get("description", "") + " " + event.get("location", "")

        # Try Google Meet
        meet_match = MEET_PATTERN.search(text_to_search)
        if meet_match:
            return meet_match.group(0)

        # Try Zoom
        zoom_match = ZOOM_PATTERN.search(text_to_search)
        if zoom_match:
            return zoom_match.group(0)

        # Try Teams
        teams_match = TEAMS_PATTERN.search(text_to_search)
        if teams_match:
            return teams_match.group(0)

        return None

    def _parse_attendees(self, attendees: list[dict]) -> list[dict]:
        """Parse attendee list into simplified format."""
        parsed = []
        for attendee in attendees:
            # Skip resources (rooms, etc.)
            if attendee.get("resource"):
                continue

            parsed.append(
                {
                    "email": attendee.get("email"),
                    "name": attendee.get("displayName", attendee.get("email", "").split("@")[0]),
                    "response": attendee.get("responseStatus", "needsAction"),
                    "self": attendee.get("self", False),
                }
            )
        return parsed

    def _parse_datetime(self, dt_string: str | None) -> datetime | None:
        """Parse ISO datetime string to timezone-aware datetime.

        Preserves original timezone info for proper conversion at display time.
        """
        if not dt_string:
            return None

        try:
            return datetime.fromisoformat(dt_string)
        except ValueError as e:
            logger.warning("Failed to parse datetime %s: %s", dt_string, e)
            return None
