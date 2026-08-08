---
id: qui-krlz
status: closed
deps: []
links: []
created: 2026-08-03T14:12:14Z
type: bug
priority: 0
assignee: Ryan Swift
tags: [audio, rust, data-integrity]
---
# Prevent audio loss and corruption in encoder pipeline

The uncommitted Rust encoder worker silently drops buffers when its pool is exhausted or a chunk exceeds capacity, allowing mic/system tracks to desynchronize. Encoder finalization errors are stored but not returned by EncoderWorker::finalize, so invalid WAVs are reported as stopped successfully. Format renegotiation is also mishandled: in-place changes never reset encoder_initialized, while switching to a differently formatted mic emits mic_switched before the worker later fails. Add loss accounting/failure signaling, propagate finalize errors, and handle format changes without corrupting or aborting recordings.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: partial only. Drop counters and stored finalize-message lookup were added, but stop() still always returns success and UI marks completed before queued finalization errors are observed; format-changing mic switches still emit success then abort; invalid renegotiation can continue under old format; duplicate error events and reconnect-stop hang remain. cargo fmt --check also fails.

**2026-08-08T15:28:55Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Rust stop/error propagation, GIL release, encoder finalization, any-loss detection, format acknowledgement, and mic handoff are regression-tested.
