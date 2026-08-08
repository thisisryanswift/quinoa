---
id: qui-7af8
status: closed
deps: []
links: []
created: 2026-08-03T14:12:57Z
type: bug
priority: 2
assignee: Ryan Swift
tags: [security, gemini, calendar]
---
# Treat calendar metadata as untrusted prompt data

Upstream 6eb199a inserts externally controlled meeting titles and attendee names directly into the transcription instruction prompt. Newline stripping/truncation does not prevent instruction injection, and structured output constrains shape rather than semantics. Delimit metadata as quoted untrusted data and explicitly instruct the model never to interpret it as instructions; add prompt construction tests.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: wrong integration point. Tests and guard cover File Search context, while ticket concerns origin/main TranscribeWorker calendar title/attendee prompt. Local branch still lacks that upstream code and remains four commits behind; integrating origin restores the vulnerable prompt unless fixed there.

**2026-08-08T15:28:56Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Calendar title/attendee and File Search context metadata are isolated as untrusted prompt data with regression tests.
