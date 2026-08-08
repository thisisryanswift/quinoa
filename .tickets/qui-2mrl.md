---
id: qui-2mrl
status: open
deps: []
links: []
created: 2026-08-08T18:07:12Z
type: chore
priority: 2
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
tags: [python, database, hygiene]
---
# Remove SQLite datetime adapter deprecation warnings

Replace reliance on Python's deprecated default SQLite datetime adapters without changing stored timestamp semantics or existing database compatibility.

## Design

Audit every datetime bind/read path in quinoa/storage/database.py. Define explicit adapters/converters or string serialization compatible with existing databases and supported Python 3.12/3.13 behavior.

## Acceptance Criteria

The Python suite passes on supported versions without SQLite default datetime-adapter deprecation warnings; existing database timestamp behavior and migrations remain compatible; focused database regression tests protect round trips.
