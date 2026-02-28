---
id: quinoa-ccc
status: closed
deps: []
links: []
created: 2025-12-09T14:46:55.560889181-05:00
type: epic
priority: 1
---
# Meeting Folders - Left Panel Organization

Transform the left panel from a flat chronological list into an organized, folder-based view.

## UI Changes
- Add Today/History toggle at top of left panel
- Today: Current view (upcoming + today's meetings, chronological)
- History: Folder-based view of all past meetings
- Folders are expandable/collapsible inline (newest meetings first)
- 'Uncategorized' folder at bottom as catch-all
- '+ New Folder' button
- **Search/filter bar** in History view to filter by meeting name or attendees

## Features
- Create/rename/delete folders
- **Nested folders supported** (e.g., '1:1s' parent folder with 'Sarah', 'Bob' subfolders)
- User-defined folder ordering (drag to reorder)
- Right-click meeting → 'Move to folder'
- Drag-and-drop meetings into folders (stretch goal)
- Smart suggestions when recurring_event_id detected (user opts in via toast/banner)
- Manual grouping for impromptu meetings
- **Simple search/filter** by meeting title or attendee names (not content)

## Database Changes
```sql
CREATE TABLE meeting_folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT REFERENCES meeting_folders(id),  -- For nested folders
    recurring_event_id TEXT,
    created_at TIMESTAMP,
    sort_order INTEGER DEFAULT 0
);

ALTER TABLE calendar_events ADD COLUMN folder_id TEXT REFERENCES meeting_folders(id);
ALTER TABLE recordings ADD COLUMN folder_id TEXT REFERENCES meeting_folders(id);
```

## Migration
- All existing meetings start in Uncategorized
- No auto-grouping on first launch

## Design Decisions
- Folder sorting: User-defined (drag to reorder)
- Meetings within folders: Newest first (chronological descending)
- Recurring suggestion UX: Toast/banner when recording a recurring meeting: 'Add to folder X?' with Yes/No
- Minimal styling for v1 (no colors/icons)
- Search filters by title/attendees only, not transcript content

## Sub-tasks
- [ ] Database schema changes (with parent_id for nesting)
- [ ] Create MeetingFolder model/methods in database.py
- [ ] Today/History toggle UI
- [ ] History view with folder tree (nested)
- [ ] Folder CRUD operations (create, rename, delete, reorder)
- [ ] Move meeting to folder (context menu)
- [ ] Smart suggestion for recurring meetings
- [ ] Persist folder collapsed/expanded state
- [ ] Search/filter bar in History view
- [ ] Filter logic for title and attendee matching


