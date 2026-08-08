---
id: qui-hnvy
status: open
deps: []
links: []
created: 2026-08-08T18:07:37Z
type: bug
priority: 1
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
tags: [safety, shutdown, hygiene]
---
# Make SIGINT shutdown preserve active recordings

Replace the current SIGINT default-handler shortcut so terminal interruption follows the application's graceful shutdown and does not risk losing an active recording.

## Design

Reproduce the shutdown path safely with mocks, route SIGINT through Qt/application cleanup, and preserve normal Ctrl+C developer ergonomics without invoking a real recording.

## Acceptance Criteria

An automated regression test proves SIGINT requests graceful cleanup; active worker/recording shutdown follows existing bounded lifecycle rules; no real user recording is needed for verification.
