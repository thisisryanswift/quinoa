---
id: quinoa-ihb
status: closed
deps: [quinoa-ccc]
links: []
created: 2025-12-09T14:47:22.691692118-05:00
type: epic
priority: 2
---
# RAG Agent Enhancements - Series Context & Memory

Enhance the RAG agent to leverage meeting folders for better context and memory.

## Prerequisites
- Depends on: Meeting Folders (quinoa-ccc)

## Features

### 1. Series-Aware Search
When user asks a question, agent can search across all meetings in a folder:
- 'What did Sarah and I discuss about the promotion?' → searches all 1:1s with Sarah
- Cite specific meetings: 'In your Nov 18 1:1, Sarah mentioned...'

### 2. Series Summarization
- 'Summarize this series' - aggregate insights across all meetings in a folder
- 'What topics come up most often in Daily Standup?'

### 3. Action Item Tracking
- 'What action items are still open from this series?'
- Track action items across meeting instances
- Surface incomplete items from previous meetings

### 4. Automatic Context Injection
When viewing a meeting in a series, automatically provide the agent with:
- Summary of last 2-3 meetings in the same series
- Open action items from the series
- Key topics/decisions from recent meetings

### 5. Meeting Memory
- 'What did we decide last time?'
- 'Remind me what Bob's concerns were'
- Cross-reference across the series

## Technical Considerations
- Update File Search sync to include folder/series metadata
- May need to adjust RAG prompts to leverage series context
- Consider token limits when injecting series history

## Sub-tasks
- [ ] Add folder metadata to File Search content
- [ ] Update RAG prompt to understand series context
- [ ] Implement series-wide search
- [ ] Add 'Summarize series' capability
- [ ] Action item tracking across series
- [ ] Automatic context injection for series meetings


