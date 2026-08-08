---
id: qui-bbvf
status: closed
deps: []
links: []
created: 2026-08-03T14:13:02Z
type: bug
priority: 2
assignee: Ryan Swift
tags: [tooling, release]
---
# Make bundle script derive repository root

Upstream 88378e5 hard-codes PROJECT_ROOT=/home/rswift/dev/quinoa, but this checkout is /home/rswift/dev/personal/quinoa, so scripts/bundle.sh fails at its first cd. Derive the root from the script directory rather than an absolute user-specific path.

## Notes

**2026-08-08T15:28:56Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. Bundle script derives project and HOME destinations; bash syntax check passed.
