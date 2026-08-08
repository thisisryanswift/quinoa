---
id: qui-tsd7
status: open
deps: []
links: []
created: 2026-08-08T18:07:24Z
type: chore
priority: 2
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
tags: [dependencies, gemini, hygiene]
---
# Audit stale dependencies and the Gemini upload workaround

Identify unused direct Python/Rust dependencies and determine whether the upload fallback for pre-0.4 google-genai behavior is still required with the locked modern SDK.

## Design

Trace imports and Cargo usage before removal. Verify current official Gemini SDK behavior before changing the fallback. Preserve lockfile minimum-release-age policy and avoid broad upgrades unrelated to proven cleanup.

## Acceptance Criteria

Every direct dependency has a demonstrated use or is removed through its package manager; the upload workaround is retained with current evidence or removed with regression coverage; lock and canonical checks pass.
