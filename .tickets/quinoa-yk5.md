---
id: quinoa-yk5
status: open
deps: []
links: []
created: 2025-12-09T15:41:01.242573792-05:00
type: epic
priority: 2
---
# Speaker Intelligence

Improve speaker identification, attribution, and persistence across meetings.

## Features

### 1. Set as Me / Channel Flip (from quinoa-jlh)
When Gemini assigns the wrong speaker as 'Me' (e.g., stereo channels are swapped):
- Add 'Set as Me' option in speaker chip menu
- Update the is_me flag for styling
- Persist the choice to database
- Re-render transcript with correct alignment

### 2. Persistent Speaker Profiles
- Remember speaker name mappings across meetings in the same folder/series
- When 'Speaker 2' is renamed to 'Sarah' in one meeting, suggest 'Sarah' in future meetings
- Store speaker profiles linked to folders (series context)

### 3. Utterance Timestamps
- Enable Gemini's audioTimestamp config parameter
- Update Utterance model to include timestamp field
- Store timestamps in database for playback sync
- Required for Search & Playback epic (click-to-jump)

### 4. Voice Fingerprinting (Stretch Goal / Future)
- NOT in v1 scope - Gemini doesn't have built-in voice recognition
- Would require separate service or custom ML solution
- Placeholder for future exploration

## Database Changes
```sql
-- Speaker profiles table
CREATE TABLE speaker_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    folder_id TEXT REFERENCES meeting_folders(id),
    voice_sample_path TEXT,  -- Future: for voice fingerprinting
    created_at TIMESTAMP
);

-- Update Utterance schema to include timestamp
-- (stored as JSON in transcripts.utterances)
```

## Sub-tasks
- [x] Add 'Set as Me' to speaker chip context menu
- [x] Persist is_me flag to database
- [x] Enable audioTimestamp in Gemini transcription config
- [x] Update Utterance Pydantic model with timestamp field
- [x] Create speaker_profiles table
- [x] Implement speaker name suggestions from profiles
- [ ] Link profiles to folders for series context (Note: Scoped globally by usage frequency >= 3 per user request instead)


