---
id: qui-e3yb
status: closed
deps: []
links: []
created: 2026-08-03T14:12:42Z
type: bug
priority: 1
assignee: Ryan Swift
tags: [tests, calendar, transcription, parsing]
---
# Make upstream tests clean and recovery semantics truthful

Origin main cannot collect tests without Calendar OAuth secrets because importing quinoa.calendar.utils eagerly imports auth and loads credentials at module import. Ruff also fails test_calendar_utils import ordering. Truncated transcript recovery deliberately drops utterances containing braces yet returns parse_error=False, so incomplete data is marked transcribed. Load OAuth lazily, fix lint, replace regex object recovery with a string-aware parser, and distinguish partial recovery from full success.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: partial. Non-dict config and brace-aware raw_decode are improved, but recovered truncated results still return parse_error=False, discard timestamps, replace DB transcript, delete action items, and trigger completion/compression/sync. Origin-only calendar/transcript tests were not integrated because branch remains behind 4 commits.

**2026-08-08T15:28:55Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Clean no-secret test collection and truthful partial transcript persistence/side-effect suppression are regression-tested.
