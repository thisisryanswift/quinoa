"""UI Stylesheets for Quinoa application.

This file contains only styles for custom widgets that need specific colors
for semantic meaning (e.g., record button = red, VU meters).

Standard widgets (lists, buttons, labels) inherit from the system theme
(Breeze on KDE) for a native look.
"""


def level_meter_style(chunk_color: str) -> str:
    """Generate a level meter stylesheet with the specified chunk color.

    These use semantic colors (green=mic, blue=system) that should
    remain consistent regardless of theme.
    """
    return f"""
        QProgressBar {{
            border: 1px solid palette(mid);
            border-radius: 3px;
            background-color: palette(base);
            height: 10px;
        }}
        QProgressBar::chunk {{
            background-color: {chunk_color};
        }}
    """


# Level meter styles - semantic colors for audio sources
LEVEL_METER_MIC = level_meter_style("#2ecc71")  # Green for microphone
LEVEL_METER_SYSTEM = level_meter_style("#3498db")  # Blue for system audio

# Recording button styles - semantic colors for recording state
BUTTON_RECORD = """
    QPushButton {
        background-color: #e74c3c;
        color: white;
        font-size: 16px;
        font-weight: bold;
        border-radius: 5px;
        padding: 8px 16px;
    }
    QPushButton:hover {
        background-color: #c0392b;
    }
    QPushButton:pressed {
        background-color: #a93226;
    }
"""

BUTTON_STOP = """
    QPushButton {
        background-color: #555;
        color: white;
        font-size: 16px;
        font-weight: bold;
        border-radius: 5px;
        padding: 8px 16px;
    }
    QPushButton:hover {
        background-color: #666;
    }
    QPushButton:pressed {
        background-color: #444;
    }
"""

BUTTON_PAUSE = """
    QPushButton {
        background-color: #f39c12;
        color: white;
        font-size: 16px;
        font-weight: bold;
        border-radius: 5px;
        padding: 8px 16px;
    }
    QPushButton:hover {
        background-color: #e67e22;
    }
    QPushButton:pressed {
        background-color: #d35400;
    }
    QPushButton:disabled {
        background-color: palette(mid);
        color: palette(disabled-text);
    }
"""

# Status label - just for the paused state color
STATUS_LABEL_PAUSED = "color: #f39c12;"  # Orange to match pause button

# Speaker colors for transcript bubbles - keep these consistent
# First color is always for "Me" (the user)
SPEAKER_COLORS = [
    "#3498db",  # Blue (Me)
    "#9b59b6",  # Purple
    "#e67e22",  # Orange
    "#1abc9c",  # Teal
    "#e74c3c",  # Red
    "#2ecc71",  # Green
    "#f39c12",  # Yellow
    "#34495e",  # Dark gray
]
