---
description: Diagnose a critical defect and generate a precision repair ticket for a Developer agent.
---

# 🔧 Skill: Create Repair Ticket (QA -> Dev Handoff)

> **Use Case**: When a generic "Fix this" is insufficient. Use this to provide a **surgical** repair plan for a Developer agent.
> **Context**: You have identified a bug, diagnosing the root cause, and need to delegate the fix.

## 1. 🕵️ Phase I: The Diagnosis

Before writing the ticket, you must confirm the **Root Cause**.
- **Trace**: Not just "it fails", but "variable X is NULL at line Y".
- **Evidence**: Start by `grep` or `cat` the failing logs.
- **Repro**: Identify the minimal repro command.

## 2. 💊 Phase II: The Prescription

Define the **Critical Fixes** necessary.
- **Code Level**: Specify the exact function/logic to change.
- **Security Check**: Did you re-enable skipped security features?
- **Performance Check**: Does this fix respect the critical path?

## 3. 📦 Phase III: The Ticket Generation

Output a code block with the following structure:

```markdown
**Role**: Developer
**Task**: [Short Title of Defect]
**Severity**: [P0/P1/P2]

**Context**:
[Brief description of the bug and its impact. e.g., "10x performance regression due to environment mismatch."]

**Critical Fixes Required**:

1.  **[File Path]**:
    *   [Instruction: e.g., "Inject VELO_PYTHON env var"]
    *   [Code Snippet/Diff]:
        ```python
        # Expected code
        ```

2.  **[Secondary Requirement]**:
    *   [Instruction: e.g., "Re-enable EnvironmentShield in mod.rs"]

**Verification Criteria**:
*   [Test Command] -> PASS
*   [Metric] -> [Target Value]
```

## 4. 📤 Phase IV: The Handoff

Present this prompt to the user and ask them to:
"Please copy this prompt and paste it to the Developer agent."
