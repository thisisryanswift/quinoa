---
id: qui-dqji
status: closed
deps: []
links: []
created: 2026-03-03T18:43:16Z
type: task
priority: 1
assignee: Ryan Swift
parent: quinoa-m7p
---
# Trigger immediate sync on meeting rename or speaker update

Emit metadata_changed signal from MiddlePanel when title or speaker names change, and connect it in MainWindow to SyncWorker.queue_for_sync with a short (e.g. 10s) delay.

