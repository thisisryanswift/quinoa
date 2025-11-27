# Granola Linux Refactoring Action Plan

This document outlines code quality issues and recommended refactoring for the Granola Linux project. Issues are organized by priority and grouped by category.

---

## Executive Summary

The codebase is functional but shows typical LLM-generated patterns: verbose inline code, duplicated logic, magic numbers, and monolithic files. The main pain point is `main_window.py` at 930 lines - a classic "god class" that handles everything from UI to business logic.

**Key metrics:**
- Python: ~1,573 lines across 6 files
- Rust: ~1,255 lines across 6 files
- Largest file: `main_window.py` (930 lines) - needs splitting

---

## High Priority

### 1. Split `main_window.py` into Smaller Components

**File:** `granola/ui/main_window.py` (930 lines)

**Problem:** This file is a monolith handling UI setup, recording logic, transcription, history management, tray icon, shortcuts, and error handling.

**Recommendation:** Split into focused modules:

```
granola/ui/
├── main_window.py          # ~150 lines - just window setup and tab coordination
├── record_tab.py           # ~250 lines - recording UI and controls
├── history_tab.py          # ~200 lines - history list and details
├── tray_icon.py            # ~60 lines - system tray functionality
├── transcribe_worker.py    # ~80 lines - QThread for transcription
├── widgets/
│   └── level_meter.py      # ~40 lines - reusable level meter widget
└── styles.py               # ~50 lines - all stylesheets as constants
```

---

### 2. Extract Duplicated Transcript Handling

**Files:** `granola/ui/main_window.py:507-549` and `granola/ui/main_window.py:896-924`

**Problem:** `on_transcription_finished` and `on_history_transcription_finished` are nearly identical (~90% overlap).

**Current code (duplicated in two places):**
```python
def on_transcription_finished(self, json_str):
    # ... 30 lines of parsing, displaying, saving

def on_history_transcription_finished(self, json_str):
    # ... same 30 lines with minor differences
```

**Recommendation:** Create a shared handler:

```python
def _handle_transcription_result(self, json_str, recording_id, transcript_display, actions_list=None):
    """Common handler for transcription results."""
    try:
        data = json.loads(json_str)
        transcript_text = data.get("transcript", "")
        summary = data.get("summary", "")
        action_items = data.get("action_items", [])

        # Format display
        display_text = self._format_transcript_display(transcript_text, summary)
        transcript_display.setText(display_text)

        # Update action items if list provided
        if actions_list:
            self._populate_action_items(actions_list, action_items)

        # Save to DB
        if recording_id:
            self.db.save_transcript(recording_id, transcript_text, summary)
            self.db.save_action_items(recording_id, action_items)

    except json.JSONDecodeError:
        transcript_display.setText(json_str)
        if recording_id:
            self.db.save_transcript(recording_id, json_str)
```

---

### 3. Extract Hard-coded Values into Constants

**Problem:** Magic numbers scattered throughout the codebase.

**Examples found:**

| Location | Value | Purpose |
|----------|-------|---------|
| `main_window.py:77` | `800, 600` | Window size |
| `main_window.py:200-201` | `15`, `20` | Layout spacing/margins |
| `main_window.py:372` | `300, 500` | Splitter sizes |
| `main_window.py:591` | `500 * 1024 * 1024` | Disk space threshold |
| `main_window.py:669` | `48000` | Sample rate |
| `main_window.py:714` | `100` | Timer interval (ms) |
| `session.rs:589` | `100` | Timer interval (ms) |
| `enumerate.rs:143-144` | `48000, 2` | Default sample rate/channels |
| `processor.py:40` | `4096` | Audio chunk size |

**Recommendation:** Create `constants.py`:

```python
# granola/constants.py

# Window
WINDOW_MIN_WIDTH = 800
WINDOW_MIN_HEIGHT = 600
SPLITTER_DEFAULT_SIZES = [300, 500]

# Layout
LAYOUT_SPACING = 15
LAYOUT_MARGIN = 20

# Audio
DEFAULT_SAMPLE_RATE = 48000
AUDIO_CHUNK_SIZE = 4096
TIMER_INTERVAL_MS = 100

# Storage
MIN_DISK_SPACE_BYTES = 500 * 1024 * 1024  # 500 MB
```

For Rust, add to `session.rs`:
```rust
const TIMER_INTERVAL_MS: u64 = 100;
const DEFAULT_SAMPLE_RATE: u32 = 48000;
const DEFAULT_CHANNELS: u8 = 2;
```

---

### 4. Consolidate Inline Stylesheets

**Problem:** Button and widget styles are defined inline, repeated multiple times.

**Files affected:** `main_window.py` lines 204, 218-228, 243-254, 268-278, 285-298, 691-701, 746-756

**Example of repetition:**
```python
# Appears twice with different colors
self.mic_level_bar.setStyleSheet("""
    QProgressBar {
        border: 1px solid #bbb;
        border-radius: 3px;
        background-color: #eee;
        height: 10px;
    }
    QProgressBar::chunk {
        background-color: #2ecc71;  # Only difference is this color
    }
""")
```

**Recommendation:** Create `styles.py`:

```python
# granola/ui/styles.py

def level_meter_style(chunk_color: str) -> str:
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

LEVEL_METER_MIC = level_meter_style("#2ecc71")  # Green
LEVEL_METER_SYSTEM = level_meter_style("#3498db")  # Blue

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

TITLE_LABEL = "font-size: 24px; font-weight: bold;"
STATUS_LABEL = "font-size: 16px; color: #666;"
STATUS_LABEL_PAUSED = "font-size: 16px; color: orange;"
```

---

### 5. Replace `print()` with Proper Logging

**Problem:** Debug output uses `print()` throughout - no log levels, no file output, no timestamps.

**Examples found:**
- `main_window.py`: 10+ print statements
- `config.py`: 4 print statements
- `gemini.py`: 2 print statements
- `session.rs`: eprintln! throughout

**Recommendation:**

```python
# granola/logging_config.py
import logging

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('~/.local/share/granola/granola.log')
        ]
    )
    return logging.getLogger('granola')

logger = setup_logging()
```

Then replace:
```python
# Before
print(f"Failed to start device monitor: {e}")

# After
logger.warning(f"Failed to start device monitor: {e}")
```

---

## Medium Priority

### 6. Add Type Hints to Python Code

**Problem:** No type hints make the code harder to understand and maintain.

**Example (current):**
```python
def add_recording(self, rec_id, title, started_at, mic_path, sys_path,
                  mic_device_id=None, mic_device_name=None, directory_path=None):
```

**Recommended:**
```python
from datetime import datetime
from pathlib import Path
from typing import Optional

def add_recording(
    self,
    rec_id: str,
    title: str,
    started_at: datetime,
    mic_path: Path | str,
    sys_path: Path | str,
    mic_device_id: Optional[str] = None,
    mic_device_name: Optional[str] = None,
    directory_path: Optional[Path | str] = None,
) -> None:
```

**Priority files:**
1. `database.py` - core data layer
2. `config.py` - configuration
3. `gemini.py` - external API
4. `processor.py` - audio processing

---

### 7. Fix Bare Exception Handling

**File:** `main_window.py:418`

**Problem:** Bare `except:` catches everything including KeyboardInterrupt, SystemExit.

```python
# Current (bad)
try:
    dt = datetime.fromisoformat(ts)
    display_ts = dt.strftime("%Y-%m-%d %H:%M")
except:
    display_ts = str(ts)
```

**Recommended:**
```python
try:
    dt = datetime.fromisoformat(ts)
    display_ts = dt.strftime("%Y-%m-%d %H:%M")
except (ValueError, TypeError) as e:
    logger.debug(f"Failed to parse timestamp {ts}: {e}")
    display_ts = str(ts)
```

---

### 8. Use serde_json for JSON Parsing in Rust

**File:** `granola_audio/src/device/enumerate.rs:54-88`

**Problem:** Manual JSON string parsing is error-prone and duplicated.

**Current code (duplicated twice):**
```rust
let name = if json_val.starts_with('{') {
    if let Some(start) = json_val.find("\"name\":") {
        let rest = &json_val[start + 7..];
        if let Some(start_quote) = rest.find('"') {
            let rest = &rest[start_quote + 1..];
            if let Some(end_quote) = rest.find('"') {
                Some(rest[0..end_quote].to_string())
            } else { None }
        } else { None }
    } else { None }
} else {
    Some(json_val.to_string())
};
```

**Recommended:**
```rust
// Add to Cargo.toml: serde_json = "1.0"

#[derive(Deserialize)]
struct DefaultDevice {
    name: String,
}

fn parse_default_device(json_val: &str) -> Option<String> {
    if json_val.starts_with('{') {
        serde_json::from_str::<DefaultDevice>(json_val)
            .ok()
            .map(|d| d.name)
    } else {
        Some(json_val.to_string())
    }
}
```

---

### 9. Create Database Constants and Helper Methods

**File:** `granola/storage/database.py`

**Problem:** Table names and column names are strings repeated throughout.

**Recommendation:**

```python
# Table names
TABLE_RECORDINGS = "recordings"
TABLE_TRANSCRIPTS = "transcripts"
TABLE_ACTION_ITEMS = "action_items"

# Common queries as class methods
class Database:
    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query with automatic connection handling."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(query, params)

    def _fetch_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        """Fetch single row as dict."""
        cursor = self._execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def _fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows as list of dicts."""
        cursor = self._execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
```

---

## Low Priority

### 10. Extract Model Name as Configuration

**File:** `granola/transcription/gemini.py:45`

**Problem:** Model name is hard-coded.

```python
# Current
model="gemini-2.0-flash"

# Recommended - add to config.py
DEFAULT_CONFIG = {
    "output_dir": os.path.expanduser("~/Music/Granola"),
    "system_audio_enabled": True,
    "mic_device_id": None,
    "gemini_model": "gemini-2.0-flash",  # New
}
```

---

### 11. Consider Connection Pooling for SQLite

**File:** `granola/storage/database.py`

**Problem:** Each method creates a new database connection.

**Note:** For SQLite this is generally fine, but if you switch to PostgreSQL or add concurrent access, you'd want pooling. Low priority for now but worth noting.

---

### 12. Separate Test Mode from Main

**File:** `granola/main.py:19-42`

**Problem:** Test-specific code mixed with production entry point.

**Recommendation:** Move to `granola/testing/headless.py` or use a proper test framework.

---

## Code Organization Summary

### Current Structure (flat)
```
granola/
├── __init__.py
├── main.py
├── config.py
├── storage/
│   └── database.py
├── transcription/
│   ├── gemini.py
│   └── processor.py
└── ui/
    ├── main_window.py  # 930 lines - too big
    └── settings_dialog.py
```

### Recommended Structure (modular)
```
granola/
├── __init__.py
├── main.py
├── constants.py              # NEW: all magic numbers
├── logging_config.py         # NEW: logging setup
├── config.py
├── storage/
│   ├── __init__.py
│   └── database.py
├── transcription/
│   ├── __init__.py
│   ├── gemini.py
│   └── processor.py
└── ui/
    ├── __init__.py
    ├── main_window.py        # Slimmed down coordinator
    ├── record_tab.py         # NEW: record tab logic
    ├── history_tab.py        # NEW: history tab logic
    ├── transcribe_worker.py  # NEW: background worker
    ├── tray_icon.py          # NEW: tray icon handling
    ├── styles.py             # NEW: all stylesheets
    ├── settings_dialog.py
    └── widgets/
        └── level_meter.py    # NEW: reusable widget
```

---

## Implementation Order

For maximum impact with minimum disruption:

1. **Week 1:** Extract constants and styles (items 3, 4)
   - Creates reusable infrastructure
   - Low risk, high visibility improvement

2. **Week 2:** Add logging (item 5)
   - Improves debuggability
   - Simple find-and-replace

3. **Week 3:** Extract duplicate transcript logic (item 2)
   - Reduces code by ~50 lines
   - Good first step toward splitting main_window

4. **Week 4+:** Split main_window.py (item 1)
   - Biggest impact but also biggest change
   - Do incrementally: tray icon first, then tabs

---

## Quick Wins (< 1 hour each)

- [ ] Replace bare `except:` with specific exceptions
- [ ] Add type hints to `gemini.py` (smallest file)
- [ ] Extract `MIN_DISK_SPACE_BYTES` constant
- [ ] Create `styles.py` with level meter styles
- [ ] Replace prints in `config.py` with logging

---

## Metrics to Track

After refactoring, aim for:
- No file over 300 lines
- No function over 50 lines
- No bare `except:` clauses
- Type hints on all public functions
- Zero `print()` statements (use logging)
