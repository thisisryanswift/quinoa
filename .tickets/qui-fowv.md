---
id: qui-fowv
status: open
deps: []
links: []
created: 2026-08-08T18:07:17Z
type: chore
priority: 2
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
tags: [rust, audio, hygiene]
---
# Establish a warning-free Clippy policy for the audio crate

Resolve the current real-audio Clippy findings and define which real/mock targets are required as an ongoing quality gate.

## Design

Review each current Clippy finding technically, especially Arc with non-Send PipeWire state. Refactor valid findings and add narrow justified allows only where the PipeWire thread model makes a lint inapplicable.

## Acceptance Criteria

Documented real/mock Clippy commands pass with the agreed warning policy; audio behavior and existing Rust tests remain green; justified lint exceptions explain the invariant they preserve.
