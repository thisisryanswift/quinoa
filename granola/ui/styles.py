"""UI Stylesheets for Granola application."""


def level_meter_style(chunk_color: str) -> str:
    """Generate a level meter stylesheet with the specified chunk color."""
    return f"""
        QProgressBar {{
            border: 1px solid #bbb;
            border-radius: 3px;
            background-color: #eee;
            height: 10px;
        }}
        QProgressBar::chunk {{
            background-color: {chunk_color};
        }}
    """


# Level meter styles
LEVEL_METER_MIC = level_meter_style("#2ecc71")  # Green
LEVEL_METER_SYSTEM = level_meter_style("#3498db")  # Blue

# Button styles
BUTTON_RECORD = """
    QPushButton {
        background-color: #e74c3c;
        color: white;
        font-size: 18px;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #c0392b;
    }
"""

BUTTON_STOP = """
    QPushButton {
        background-color: #333;
        color: white;
        font-size: 18px;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #555;
    }
"""

BUTTON_PAUSE = """
    QPushButton {
        background-color: #f39c12;
        color: white;
        font-size: 18px;
        border-radius: 5px;
    }
    QPushButton:hover {
        background-color: #e67e22;
    }
    QPushButton:disabled {
        background-color: #bdc3c7;
    }
"""

# Label styles
TITLE_LABEL = "font-size: 24px; font-weight: bold;"
STATUS_LABEL = "font-size: 16px; color: #666;"
STATUS_LABEL_PAUSED = "font-size: 16px; color: orange;"
