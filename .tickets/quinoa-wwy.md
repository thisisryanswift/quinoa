---
id: quinoa-wwy
status: closed
deps: []
links: []
created: 2025-12-09T08:07:34.330100269-05:00
type: bug
priority: 2
---
# File Search Duplicate Prevention

Re-transcribing a meeting uploads a new file to Gemini File Search without removing the old one.
Proposed solution:
- Check if file deletion API is now available
- If not, track file IDs and implement cleanup
- Or use content deduplication on query side


