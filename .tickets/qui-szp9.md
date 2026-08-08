---
id: qui-szp9
status: closed
deps: []
links: []
created: 2026-08-03T14:12:21Z
type: bug
priority: 1
assignee: Ryan Swift
tags: [python, workers, calendar, gemini]
---
# Restore worker error handling for network failures

Uncommitted exception narrowing omits real transport/server exceptions. Calendar credential refresh raises google.auth.exceptions.TransportError (not requests.RequestException), which can abort startup offline. Calendar API transport failures can kill sync. Gemini ServerError/httpx failures bypass transcription, chat, enhancement, and File Search sync error signals, leaving controls disabled or workers dead. Catch each SDK's actual operational exception family and ensure every QThread terminal path restores UI state.


## Notes

**2026-08-07T22:46:22Z**

Audit 2026-08-03: unresolved. Gemini httpx.ConnectError/Timeout still escape APIError handlers and leave transcription/chat/enhancement/sync without error signals. Calendar google-api-python-client httplib2 transport errors remain uncaught. ensure_store_exists now treats every APIError including 5xx as missing and may create duplicate stores. Reproduced ConnectError escaping FileSearchManager.query.

**2026-08-08T15:28:55Z**

Verified on reconciled main 80b94f4: pytest tests/python/ 118 passed; ruff quinoa/tests passed; mypy quinoa/tests passed; cargo fmt + real/mock cargo check passed; real-audio cargo test 18 passed; uv lock/diff/shell checks passed; mock maturin build and application smoke test passed. httpx/API/httplib2 boundaries, 404-vs-5xx behavior, worker signals, cancellation, and backfill recovery are regression-tested.
