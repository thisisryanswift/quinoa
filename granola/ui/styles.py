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

# Splitter style - wider handle for easier grabbing
# Uses transparent background with subtle hover/press feedback
SPLITTER_STYLE = """
    QSplitter::handle {
        background-color: transparent;
    }
    QSplitter::handle:horizontal {
        width: 6px;
    }
    QSplitter::handle:vertical {
        height: 6px;
    }
    QSplitter::handle:hover {
        background-color: rgba(128, 128, 128, 0.3);
    }
    QSplitter::handle:pressed {
        background-color: rgba(128, 128, 128, 0.5);
    }
"""

# Rich text editor styles
RICH_EDITOR_STYLE = """
    QTextEdit {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', sans-serif;
        font-size: 14px;
        padding: 12px;
        border: none;
        background-color: #1e1e1e;
        color: #e0e0e0;
    }
"""

RICH_EDITOR_TOOLBAR_STYLE = """
    QToolBar {
        background-color: #2d2d2d;
        border-bottom: 1px solid #404040;
        spacing: 2px;
        padding: 4px;
    }
    QToolButton {
        background-color: transparent;
        border: none;
        border-radius: 4px;
        padding: 4px 8px;
        color: #e0e0e0;
        font-size: 13px;
        min-width: 24px;
    }
    QToolButton:hover {
        background-color: #404040;
    }
    QToolButton:checked {
        background-color: #0066cc;
    }
    QToolButton:pressed {
        background-color: #505050;
    }
    QToolButton::menu-indicator {
        image: none;
        width: 0;
    }
"""

# View selector tab-style buttons for historic meeting views
VIEW_SELECTOR_STYLE = """
    QPushButton {
        background-color: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 8px 16px;
        color: #888;
        font-size: 14px;
    }
    QPushButton:checked {
        color: #fff;
        border-bottom: 2px solid #3498db;
    }
    QPushButton:hover {
        color: #bbb;
    }
    QPushButton:disabled {
        color: #555;
    }
"""

# Meeting header styles
MEETING_HEADER_TITLE = """
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
    padding: 0;
    margin: 0;
"""

MEETING_HEADER_CHIP = """
    QLabel {
        background-color: #2d2d2d;
        color: #aaa;
        border-radius: 10px;
        padding: 4px 10px;
        font-size: 12px;
    }
"""

# Left panel meeting list styles
MEETING_LIST_STYLE = """
    QListWidget {
        background-color: transparent;
        border: none;
        outline: none;
    }
    QListWidget::item {
        padding: 8px 4px;
        border-bottom: 1px solid #333;
    }
    QListWidget::item:selected {
        background-color: #2d4a6d;
        border-radius: 4px;
    }
    QListWidget::item:hover {
        background-color: #333;
    }
"""

DATE_GROUP_HEADER_STYLE = """
    font-size: 11px;
    font-weight: bold;
    color: #888;
    padding: 8px 4px 4px 4px;
    text-transform: uppercase;
"""

# Speaker colors for transcript bubbles
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
