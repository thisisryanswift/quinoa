---
id: qui-ogi8
status: open
deps: []
links: []
created: 2026-08-08T18:07:31Z
type: chore
priority: 3
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
tags: [tests, coverage, hygiene]
---
# Define Python coverage reporting and a meaningful threshold

Measure current meaningful Python coverage, identify risk-based gaps, and choose a non-arbitrary enforcement threshold before adding coverage to the canonical gate.

## Design

Prefer observable behavior and critical audio/database/worker seams over line-count gaming. Establish a reviewed baseline before enforcing a threshold or adding a coverage dependency.

## Acceptance Criteria

Coverage can be reproduced locally and in CI; the chosen threshold is justified from measured baseline and risk; exclusions are explicit; canonical checks remain deterministic.
