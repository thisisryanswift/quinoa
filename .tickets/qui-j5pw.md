---
id: qui-j5pw
status: open
deps: []
links: []
created: 2026-08-08T18:07:48Z
type: chore
priority: 2
assignee: Ryan Swift
external-ref: docs/designs/2026-08-08-agent-ready-repository.md#ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
tags: [tickets, roadmap, hygiene]
---
# Reconcile closed product epics with ROADMAP scope

Audit closed epics whose unchecked scope still appears in ROADMAP and make the durable product backlog truthful without silently declaring unresolved ideas complete.

## Design

Compare closed Ticket acceptance/checklists to observable code and ROADMAP claims. Preserve historical notes. Reopen work or create focused replacement tickets only after product intent is confirmed.

## Acceptance Criteria

Closed epic status, remaining ROADMAP plans, and replacement/open tickets agree; historical completion evidence is preserved; no unresolved product behavior is marked complete based only on ticket status.
