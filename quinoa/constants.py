"""Constants for Quinoa application."""

import os
from datetime import datetime
from enum import IntEnum

# Gemini Models
GEMINI_MODEL_TRANSCRIPTION = "gemini-2.5-flash"  # 65K output tokens (2.0-flash only has 8K)
GEMINI_MODEL_SEARCH = "gemini-2.5-flash"

# Window dimensions
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 600

# Panel dimensions (3-column layout)
LEFT_PANEL_WIDTH = 260
LEFT_PANEL_MIN_WIDTH = 200
RIGHT_PANEL_WIDTH = 300
SPLITTER_DEFAULT_SIZES = [LEFT_PANEL_WIDTH, 440, RIGHT_PANEL_WIDTH]

# Layout
LAYOUT_SPACING = 15
LAYOUT_MARGIN = 20
LAYOUT_MARGIN_SMALL = 10

# Audio
DEFAULT_SAMPLE_RATE = 48000
AUDIO_CHUNK_SIZE = 4096
TIMER_INTERVAL_MS = 100

# Storage
MIN_DISK_SPACE_BYTES = 500 * 1024 * 1024  # 500 MB

# Notes
NOTES_AUTO_SAVE_INTERVAL_MS = 30000  # 30 seconds

# File Search
FILE_SEARCH_DELAY_MS = 5 * 60 * 1000  # 5 minutes before sync
FILE_SEARCH_POLL_INTERVAL_MS = 60 * 1000  # Check every minute
MIN_SYNC_DURATION_SECONDS = 30  # Skip recordings shorter than 30s
CHAT_MAX_HISTORY = 50  # Max messages to retrieve


class PanelMode(IntEnum):
    """Mode for the middle panel."""

    IDLE = 0
    RECORDING = 1
    VIEWING = 2


class ViewType(IntEnum):
    """View type when in viewing mode."""

    NOTES = 0
    TRANSCRIPT = 1
    ENHANCED = 2


# Unicode icons for UI
ICON_CHECKMARK = "\u2713"  # ✓
ICON_PLAY = "\u25b6"  # ▶
ICON_CIRCLE_EMPTY = "\u25cb"  # ○
ICON_BULLET = "\u2022"  # •
ICON_CALENDAR = "\U0001f4c5"  # 📅
ICON_STOPWATCH = "\u23f1"  # ⏱


def get_now() -> datetime:
    """Return the current datetime, or a spoofed date if QUINOA_DATE_OVERRIDE is set.

    Set QUINOA_DATE_OVERRIDE to an ISO date (e.g. '2026-03-02') to test the UI
    as if it were a different day. Time-of-day is preserved from the real clock.
    """
    override = os.environ.get("QUINOA_DATE_OVERRIDE")
    if override:
        try:
            fake_date = datetime.fromisoformat(override).date()
            real_now = datetime.now()
            return real_now.replace(year=fake_date.year, month=fake_date.month, day=fake_date.day)
        except ValueError:
            pass
    return datetime.now()
