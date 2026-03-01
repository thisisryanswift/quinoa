# Quinoa Roadmap

## Recently Completed

### Session: 2026-03-01

**Speaker Intelligence (Epic):**
- **Persistent Speaker Profiles**: Automatically tracks frequent contacts (>= 3 meetings) globally.
- **Smart Suggestions**: Editable dropdown for speaker renaming with frequency-based autocomplete.
- **"Set as Me" / Channel Flip**: Instantly correct speaker misattribution via context menu; bubbles flip sides and update styles.
- **Native Sync**: Enabled Gemini `audio_timestamp` for reliable millisecond-accurate utterance timing.

**Search, Discovery & Playback (Epic):**
- **Click-to-Jump**: Each chat bubble has a clickable `▶ MM:SS` timestamp that seeks the audio player.
- **Playback Sync**: Karaoke-style highlighting; the active bubble styles itself and auto-scrolls as audio plays.
- **Search Navigation**: Clicking a snippet in the history search bar now jumps directly to that meeting, highlights the matching text, and scrolls to the utterance.

**Linux Desktop Integration:**
- **Rich D-Bus Notifications**: Upgraded from Qt toasts to native KDE/GNOME notifications using `jeepney`.
- **Interactive Actions**: "Start Recording" button directly in the notification starts recording immediately.
- **Headless Safety**: One-click recording still performs disk space and Bluetooth A2DP safety checks before starting.

### Session: 2026-02-28

**Daily Driver Features:**
- Auto-transcribe: recordings automatically sent to Gemini when you stop recording (configurable in Settings)
- Meeting notifications: desktop notifications 5 minutes before meetings via system tray
- Recording reminders: persistent notification if a meeting started but you haven't begun recording
- New Settings UI groups: "Automation" and "Notifications" with granular toggles
- Notification worker: background thread polls calendar events every 30 seconds
- Auto-stop recording: detect extended silence and prompt user to stop
- Gemini model configurability: choose between models (2.5-flash, 2.5-pro, etc.) in Settings

**Resilience & Recovery:**
- Robust Google Calendar authentication recovery (handles `invalid_grant` and expired tokens)
- AI Transcription recovery: regex-based parser extracts utterances even from truncated Gemini responses
- Migrated task tracking from `beads` to `ticket` (`tk`)

**UI Polish & Layout Overhaul:**
- Wider left panel with tooltips on truncated items
- Empty state for middle panel
- Increased left panel item padding
- Date grouping headers in meeting list
- Clearer Today/History tab active state
- Collapsible recording toolbar
- Inline dates in Uncategorized section
- Hide VU meters when not recording

### Session: 2025-12-09 through 2025-12-11

**Meeting Folders (Epic):**
- Folder-based organization in left panel (replaces flat chronological list)
- Smart folder suggestions for recurring meetings
- Search filter within folder view
- Show unrecorded past meetings in history tree

**Features Added:**
- Full-text search for transcripts (SQLite FTS)
- Audio player in transcript view with mixing for playback
- Transcript export as markdown/plain text
- Notes/transcript indicators (icons) in history view
- Notes for unrecorded meetings
- Audio channel flip / "Set as Me" for speaker assignment
- File Search duplicate prevention (cleanup on re-transcribe)
- Delete/suppress meetings from list
- Respect selected meeting in recording popup

**Code Quality:**
- Post-AI audit cleanup and project hygiene

### Session: 2025-12-08

**Features Added:**
- Seamless mic switching during recording (Rust + Python integration)
- Audio compression: WAV→FLAC after transcription (~50% space savings)
- Background compression worker for existing recordings

**Code Quality:**
- Database connection pooling (thread-local connections)
- Extracted icon constants to `constants.py`
- Removed OAuth secrets from documentation

### Session: 2025-12-07

**P1 Fixes (Calendar Integration):**
- Fixed `sync_now()` UI freeze with QMutex/QWaitCondition
- Moved OAuth credentials to `secrets.json` + env vars
- Fixed brittle timezone handling (preserve TZ, convert at display)
- Removed dead code (`list_calendars()`, `_add_unlinked_recordings_for_date()`)

**P2 Fixes:**
- Database connection pooling
- Reduced nesting in meeting selection dialog
- Extracted magic strings to constants

### Session: 2025-12-04

**Bugs Fixed:**
- Raw JSON displayed instead of chat bubbles (markdown fence stripping + mode check)
- "Device removed: None" spam in terminal (filter spurious events)
- Long meetings truncated mid-transcript (Gemini 2.0-flash 8K token limit -> switched to 2.5-flash with 65K limit)
- Meeting rename not syncing between left panel and header

**Features Added:**
- Speaker diarization with chat bubbles in transcript view
- Speaker chips in meeting header (clickable to rename)
- Click-to-rename meeting title in header
- Speaker rename/reassign from transcript (click speaker name)

---

## Planned Features

### High Priority

#### Trim Feature Polish & Testing
The Trim UI and logic are implemented but have zero test coverage.
- [ ] Add unit tests for `trimmer.py` logic (silence detection, region merging).
- [ ] Add tests for `waveform_widget.py` (cut management and UI logic).

### Medium Priority

#### RAG Agent Enhancements - Series Context & Memory (Epic)
Leverage meeting folders for better AI context and memory.

- **Series-Aware Search**: Search across all meetings in a folder ("What did Sarah and I discuss about the promotion?").
- **Series Summarization**: Aggregate insights across folder ("What topics come up most in Daily Standup?").
- **Action Item Tracking**: Track action items across meeting instances, surface incomplete items.
- **Automatic Context Injection**: Provide agent with summaries from last 2-3 meetings in the same series.

### Low Priority

#### Multi-User / Enterprise Support
Future consideration for teams.
- Shared folders
- Collaborative notes
- Teams integration

---

## Known Limitations

- **Speaker Diarization**: Depends on stereo channel separation; mono recordings get all utterances as "Me"
- **Output Token Limits**: Even with 2.5-flash (65K tokens), very long meetings (2+ hours) may still truncate

---

## Future Ideas (Not Yet Planned)

Ideas captured for future consideration. Not currently scoped or prioritized.

### Export & Sharing
- Export meeting notes to PDF
- Obsidian vault integration (write .md files to user's vault)
- Share meeting summary via email/Slack

### Action Item Tracking
- Standalone "Action Items" view across all meetings
- Mark items complete/incomplete
- Assign action items to people
- Integration with Todoist or other task managers

### Meeting Templates & Prep
- Pre-meeting templates (agenda, questions to ask)
- Auto-populate notes with template when meeting starts
- "Prep" tab showing context from previous meetings in series
- AI-generated suggested questions based on past meetings

### Analytics & Insights
- Meeting time stats (hours/week in meetings)
- Trends over time
- "You discussed X topic 5 times this month"
- Which meetings run over time?
- Speaker talk-time analysis

---

## Completed Milestones

### V9 - Intelligence & Interaction (Mar 2026)
- Speaker Intelligence: Persistent profiles and smart suggestions
- Sync & Playback: Click-to-jump timestamps and active highlighting
- Linux Integration: Rich D-Bus notifications with interactive buttons

### V8 - Organization & Polish (Dec 2025 - Feb 2026)
- Meeting folders with smart suggestions for recurring meetings
- Full-text transcript search
- Audio player in transcript view
- Transcript export (markdown/plain text)
- Notes for unrecorded meetings
- Audio channel flip / "Set as Me"
- File Search duplicate prevention
- Delete/suppress meetings
- Auto-stop recording on extended silence
- Gemini model configurability
- UI polish overhaul (layout, spacing, indicators)
- Auto-transcribe after recording stops
- Meeting notifications via system tray
- Recording reminders

### V7 - Daily Driver (Feb 2026)
- Auto-transcribe after recording stops
- Meeting notifications via system tray
- Recording reminders when meetings start
- Settings UI for automation and notification preferences

### V6 - Audio Improvements (Dec 2025)
- Seamless mic switching during recording
- WAV->FLAC compression after transcription
- Background compression worker

### V5 - Google Calendar Integration (Dec 2025)
- OAuth authentication with secure credential storage
- Meetings-first calendar view
- Automatic recording-to-meeting linking
- Background calendar sync

### V4 - WYSIWYG & Views (Dec 2025)
- Rich text markdown editor for notes
- View selector (Notes / Transcript / Enhanced)
- AI-enhanced notes generation

### V3 - File Search & AI Chat (Dec 2025)
- Gemini File Search integration
- "Ask about your meetings" AI assistant
- Background sync worker

### V2 - Three Column Layout (Dec 2025)
- Left panel: Meeting list with date grouping
- Middle panel: Notes/transcript viewer
- Right panel: AI assistant chat
