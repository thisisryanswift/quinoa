---
id: quinoa-m7p
status: open
deps: [quinoa-yk5]
links: []
created: 2025-12-09T15:41:27.546288955-05:00
type: epic
priority: 2
---
# Search, Discovery & Playback

Full-text search across transcripts with integrated audio playback.

## Features

### 1. Transcript Search
- Search box in middle panel or dedicated search view
- Full-text search across all meeting transcripts
- Results show matching snippets with context
- Filter by date range, folder, attendees
- Highlight search terms in results

### 2. Audio Playback
- Inline audio player in transcript view (not a separate tab)
- Play/pause button
- Playback speed controls (0.5x, 1x, 1.5x, 2x)
- Progress bar with seeking
- Current time / total duration display

### 3. Click-to-Jump (Transcript ↔ Audio Sync)
- Click on any utterance → jump audio to that timestamp
- Requires timestamps from Speaker Intelligence epic (quinoa-yk5)
- Highlight currently playing utterance
- Auto-scroll transcript as audio plays (optional)

### 4. Search Result Navigation
- Click search result → opens meeting at that point
- Jump directly to the matched utterance
- Play audio from that timestamp

## Prerequisites
- Depends on: Speaker Intelligence (quinoa-yk5) for utterance timestamps

## Technical Considerations
- Use QMediaPlayer for audio playback in PyQt6
- Index transcripts for fast full-text search (SQLite FTS5?)
- Store audio file paths in recordings table (already exists)

## UI Mockup
```
┌─────────────────────────────────────────┐
│ [▶] advancement and customer s... 1:23  │  ← Mini player bar
│ ━━━━━━━●━━━━━━━━━━━━━━━━━  1.5x         │
├─────────────────────────────────────────┤
│ 🔍 Search transcripts...                │
├─────────────────────────────────────────┤
│ [Notes] [Transcript] [Enhanced]         │
│                                         │
│ ▶ 0:00 Speaker A                        │  ← Click to jump
│   Welcome everyone to today's meeting   │
│                                         │
│ ▶ 0:15 Speaker B                        │  ← Currently playing
│   Thanks for having me...               │    (highlighted)
└─────────────────────────────────────────┘
```

## Sub-tasks
- [ ] Add audio player widget to transcript view
- [ ] Implement playback controls (play/pause, seek, speed)
- [ ] Store/retrieve utterance timestamps
- [ ] Implement click-utterance-to-seek
- [ ] Add search box UI
- [ ] Implement SQLite FTS5 for transcript search
- [ ] Search results view with snippets
- [ ] Search result → jump to meeting/timestamp


