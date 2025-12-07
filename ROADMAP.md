# Quinoa Roadmap

## Recently Completed

### Session: 2025-12-04

**Bugs Fixed:**
- Raw JSON displayed instead of chat bubbles (markdown fence stripping + mode check)
- "Device removed: None" spam in terminal (filter spurious events)
- Long meetings truncated mid-transcript (Gemini 2.0-flash 8K token limit → switched to 2.5-flash with 65K limit)
- Meeting rename not syncing between left panel and header

**Features Added:**
- Speaker diarization with chat bubbles in transcript view
- Speaker chips in meeting header (clickable to rename)
- Click-to-rename meeting title in header
- Speaker rename/reassign from transcript (click speaker name)

---

## Planned Features

### High Priority

#### Audio Channel Flip / "Set as Me"
When Gemini assigns the wrong speaker as "Me" (e.g., stereo channels are swapped), users need a way to designate which speaker is actually them.

**Proposed solution:** Add "Set as Me" option in speaker menu that:
- Updates the `is_me` flag for styling
- Persists the choice to database
- Re-renders transcript with correct alignment

#### Trim Recording UI
Users sometimes forget to stop recordings. Currently requires manual ffmpeg trimming.

**Proposed solution:**
- Waveform visualization in recording view
- Drag handles to select trim points
- Silence detection to suggest cut points
- "Trim" button to truncate audio files and update duration

### Medium Priority

#### Storage Optimization
Current format: Uncompressed WAV at 48kHz stereo
- ~16.8 MB/minute
- ~1 GB/hour
- ~1 TB/year at 20 hours/week

**Proposed solutions:**
- Switch to Opus codec (~15 MB/hour, 98% reduction)
- Or FLAC for lossless (~50% reduction)
- Consider 16kHz sample rate (sufficient for speech)
- Option to compress after transcription completes

#### File Search Duplicate Prevention
Re-transcribing a meeting uploads a new file to Gemini File Search without removing the old one, causing duplicates.

**Proposed solution:**
- Check if file deletion API is now available
- If not, track file IDs and implement cleanup
- Or use content deduplication on query side

### Low Priority

#### Gemini Model Configurability
Allow users to choose between Gemini models (2.5-flash, 2.5-pro, etc.) based on their needs and quota.

#### Auto-Stop Recording
Detect extended silence and prompt user to stop recording, or auto-stop after configurable threshold.

---

## Known Limitations

- **File Search API**: May not support individual file deletion (needs verification)
- **Speaker Diarization**: Depends on stereo channel separation; mono recordings get all utterances as "Me"
- **Output Token Limits**: Even with 2.5-flash (65K tokens), very long meetings (2+ hours) may still truncate

---

## Completed Milestones

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
