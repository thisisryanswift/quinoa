---
id: qui-tihw
status: closed
deps: []
links: []
created: 2026-08-03T14:12:33Z
type: bug
priority: 0
assignee: Ryan Swift
tags: [audio, ffmpeg, transcription]
---
# Preserve full duration and atomicity in stereo mixing

Upstream commit 734c801 replaces longest-duration padding with an ffmpeg join graph that ends at the shorter input; a 2s mic plus 5s system track produces a 2s mix, dropping the remainder. TranscribeWorker also writes directly to mixed_stereo.wav and reuses any existing file, so cancelled/failed ffmpeg runs poison retries with partial audio. Pad to the longest input and write to a temporary file that is validated and atomically renamed.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: newly broken. FFmpeg temp names end in .tmp (e.g. .flac.tmp/.wav.tmp), so FFmpeg cannot infer muxer; reproduced compression and converter mixing returning None. Converter amix is mono, not channel-separated stereo. Python processor overshoots final duration to full chunk. Local fixes target processor.py, which origin/main deletes.

**2026-08-08T15:28:55Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Exact longest-duration stereo mixing, channel separation/downmix, atomic temp cleanup, cancellation, diagnostics, and converter behavior are regression-tested with real ffmpeg.
