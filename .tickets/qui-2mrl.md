---
id: qui-2mrl
status: in_progress
deps: []
links: []
created: 2026-08-08T18:07:12Z
type: chore
priority: 2
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-explicit-sqlite-datetimes.md#767811d03a62adb84684d1364804d360f50aa69ff4dc519d6ac8af041ca3e236
tags: [python, database, hygiene]
---
# Migrate SQLite timestamps to canonical UTC

Replace mixed implicit timestamp storage with fixed-width aware UTC ISO text and migrate existing rows under an explicit New York legacy assumption.

## Design

Implement docs/designs/2026-08-08-explicit-sqlite-datetimes.md at its approved body hash, including strict versioned migration, pre-write backup, canonical writes/query bounds, and local display conversion.

## Acceptance Criteria

Every timestamp column migrates once to canonical UTC; populated file databases receive a non-overwritten backup; malformed or DST-indeterminate rows roll back; new writes/query bounds are explicit and warning-free; local display/grouping remains correct; canonical local and hosted checks pass.

## Notes

**2026-08-08T19:57:13Z**

Focused migration design approved 2026-08-08. Previous parent design: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017. Approved canonical UTC design: docs/designs/2026-08-08-explicit-sqlite-datetimes.md#767811d03a62adb84684d1364804d360f50aa69ff4dc519d6ac8af041ca3e236. User also authorized post-verification migration of exact source /home/rswift/.local/share/quinoa/quinoa.db with non-overwritten backup /home/rswift/.local/share/quinoa/quinoa.db.pre-utc-v1.bak, after verifying Quinoa is stopped and backup path remains free.

**2026-08-08T20:04:56Z**

Implementation delegation note: the configured SWE worker failed to connect on two bounded attempts before making changes. No source files were modified by the worker. The parent agent is continuing the approved TDD implementation directly rather than retrying the same blocker class.

**2026-08-08T20:24:53Z**

Fresh pre-production evidence on approved design 767811d03a62adb84684d1364804d360f50aa69ff4dc519d6ac8af041ca3e236: warning-as-error focused suite passes 40 tests; full canonical gate passes 163 Python tests with no SQLite datetime warnings, 12 mock and 17 real Rust tests, formatting/lint/Mypy, and restores the real extension. Migration tests cover every column, UTC/NYC/chat policies, malformed and DST-indeterminate rollback, backup integrity/non-overwrite, version idempotency, in-memory isolation, concurrent initialization, summer/winter query bounds, and display UTC boundaries. Independent review reports no material defects after focused consumer/backup improvements. Production database remains unopened.
