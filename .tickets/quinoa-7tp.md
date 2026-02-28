---
id: quinoa-7tp
status: closed
deps: []
links: []
created: 2025-12-09T12:21:01.643057032-05:00
type: feature
priority: 2
---
# Enable notes for unrecorded meetings

Allow users to take notes for meetings that weren't recorded.
Plan:
1. Add 'notes' column to 'calendar_events' table.
2. Update MiddlePanel to show Notes tab for calendar events.
3. Disable Transcript/Enhanced tabs for unrecorded events.
4. Handle saving notes to calendar_events table.
5. Migrate notes to recording if recording starts.


