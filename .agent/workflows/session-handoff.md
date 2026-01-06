---
description: Standard protocol for ending a session and generating a context handoff prompt for the next agent.
---

1. **Review Context**: Analyze `task.md`, `REPORT.md` (if benchmark related), and `git status` to capture the session's achievements.

2. **Generate Handoff Prompt**: output a Markdown block formatted as follows:

   ```markdown
   # Context Handoff: [Project/RFC Name]

   **Status**: [Complete/InProgress]
   - **Achievement**: [Brief summary of what was done]
   - **Key Changes**: [List of critical fixes or optimizations]

   **Available Tools**:
   - [List relevant workflows or scripts created/verified]

   **Current State**:
   - Branch: [Current Git Branch]
   - Artifacts: [Paths to key data sources]

   **Next Objective**:
   (Placeholder for user to fill)
   ```

3. **Instructions to User**: Advise the user to copy this block to the next chat session.
