---
id: qui-u8vi
status: closed
deps: []
links: []
created: 2026-08-03T14:12:28Z
type: bug
priority: 1
assignee: Ryan Swift
tags: [audio, python, tests]
---
# Harden streaming trimmer analysis and failure paths

The uncommitted streaming analyser accepts short/truncated WAV payloads while reporting header-declared duration and frames, yielding misleading trailing zero bins and inconsistent silence ranges. Narrowed ffmpeg catches can also let decoding errors escape AnalysisWorker/TrimWorker without a finished signal. Validate consumed frames against declared frames, cover malformed WAV/EOFError, and guarantee worker completion/error signals. Add exact bin/chunk-boundary and 24/32-bit tests.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: unresolved. Truncated WAV duration is corrected but bins are still assigned using header_n_frames, producing trailing zero bins; EOFError still escapes; trim subprocesses still omit errors=replace/UnicodeError handling and workers can emit no completion; required malformed/chunk/24/32-bit tests were not added. Reproduced 500/1000-frame waveform with half zero bins and empty WAV EOFError.

**2026-08-08T15:28:55Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Truncated/malformed WAV handling, bounded two-pass bins, worker completion, partial trim failure, and 24/32-bit cases are regression-tested.
