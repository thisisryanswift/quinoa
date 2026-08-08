---
id: qui-r75a
status: closed
deps: []
links: []
created: 2026-08-03T14:12:52Z
type: bug
priority: 2
assignee: Ryan Swift
tags: [search, sync, ui]
---
# Resync File Search after non-viewed meeting renames

Upstream 6eb199a emits metadata_changed from MiddlePanel.on_meeting_renamed only when the renamed recording is currently viewed. Renaming another recording through CalendarPanel updates SQLite but never queues File Search re-upload, leaving the cloud document title stale. Emit/queue metadata changes independently of current selection.

## Notes

**2026-08-08T15:28:56Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Rename/metadata changes persist pending sync state and startup backfill includes pending/transcribed recordings.
