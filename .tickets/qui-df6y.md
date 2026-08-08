---
id: qui-df6y
status: closed
deps: []
links: []
created: 2026-08-03T14:12:37Z
type: bug
priority: 0
assignee: Ryan Swift
tags: [ui, pyqt, transcription]
---
# Fix transcription multitasking lifecycle regressions

Upstream commits 88378e5/734c801 introduce two P1 lifecycle defects: stopping recording A while viewing historical meeting B leaves mode IDLE and B selected, so A's auto-transcription overwrites B's visible transcript; quitting while Gemini upload/generation is blocked calls worker.wait() without timeout on the GUI thread and can hang indefinitely. Gate UI updates on the actual visible recording and make shutdown bounded/cancellable.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: visible gating overcorrects: IDLE just-finished current recording is never considered visible, so auto-transcription leaves UI stuck Transcribing despite saving DB. Shutdown cannot cancel synchronous Gemini I/O and uses unsafe QThread.terminate(), then drops the reference even if still running. Fix is also against pre-origin TranscriptionManager architecture.

**2026-08-08T15:28:55Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Lifecycle isolation, bounded cancellation, unconditional worker cleanup, and failed-finalize handling are regression-tested.
