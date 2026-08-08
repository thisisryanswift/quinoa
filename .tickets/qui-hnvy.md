---
id: qui-hnvy
status: closed
deps: []
links: []
created: 2026-08-08T18:07:37Z
type: bug
priority: 1
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-graceful-sigint-shutdown.md#38a8ed2a14a8abd1b6efd78b517c8b3301f4f0d34588a4acf546962742c76ac2
tags: [safety, shutdown, hygiene]
---
# Make SIGINT shutdown preserve active recordings

Replace the current SIGINT default-handler shortcut so terminal interruption follows the application's graceful shutdown and does not risk losing an active recording.

## Design

Reproduce the shutdown path safely with mocks, route SIGINT through Qt/application cleanup, and preserve normal Ctrl+C developer ergonomics without invoking a real recording.

## Acceptance Criteria

An automated regression test proves SIGINT requests graceful cleanup; active worker/recording shutdown follows existing bounded lifecycle rules; no real user recording is needed for verification.

## Notes

**2026-08-08T19:04:44Z**

Implementation design approved 2026-08-08. Previous parent design reference: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017. Approved focused design: docs/designs/2026-08-08-graceful-sigint-shutdown.md#f7699cd394a68796276c71687466dbed921d478b08b6ecd9385d46219032b35d. Execution authorized.

**2026-08-08T19:12:13Z**

Implementation blocker: a disposable child-process diagnostic sent real SIGINT while a minimal QApplication was idle in app.exec(). The process did not exit, proving the Python-level handler never ran to write the self-pipe. Existing unit tests were insufficient because they invoked the handler directly. Root cause: CPython defers Python signal callbacks until bytecode executes, while the idle Qt loop remains in C++. Required correction: use signal.set_wakeup_fd on the nonblocking pipe so CPython C-level signal delivery wakes QSocketNotifier; keep the Python handler as a no-op. Worktree preserved pending design revision and reapproval.

**2026-08-08T19:19:33Z**

Design reapproved 2026-08-08 after real child-process SIGINT diagnostic invalidated Python-handler pipe writes. Old focused hash: f7699cd394a68796276c71687466dbed921d478b08b6ecd9385d46219032b35d. New approved hash: 38a8ed2a14a8abd1b6efd78b517c8b3301f4f0d34588a4acf546962742c76ac2. Revised mechanism uses CPython signal.set_wakeup_fd, no-op Python handler, previous wakeup/handler restoration, partial-setup rollback, direct-pipe unit tests, and a bounded child real-SIGINT diagnostic. Execution reauthorized.

**2026-08-08T19:27:10Z**

Fresh verified implementation on approved design 38a8ed2a14a8abd1b6efd78b517c8b3301f4f0d34588a4acf546962742c76ac2: initial Python-handler self-pipe implementation failed a bounded real child SIGINT diagnostic and was replaced with CPython signal.set_wakeup_fd. Corrected child diagnostic emitted ready then quit-requested and exited 0. New shutdown suite passes 21 tests; full canonical gate passes 139 Python tests with 27 pre-existing SQLite warnings, 12 mock Rust tests, 17 real-audio Rust tests, format/lint/Mypy/checks, and restores the real extension. Independent review and focused re-review report no material findings; git diff --check is clean.

**2026-08-08T19:30:36Z**

Hosted CI run 31274477481 passed on commit 74e8b4a. Verified: 139 Python tests including 21 shutdown regressions, mock/real Rust checks and tests, real extension restoration, formatting/lint/Mypy, and clean Ubuntu dependencies. The bounded child-process real SIGINT diagnostic also emitted ready then quit-requested and exited 0 with no fallback timer or user data. Remaining CI annotation is the pre-existing non-fatal Node 20 action deprecation warning.
