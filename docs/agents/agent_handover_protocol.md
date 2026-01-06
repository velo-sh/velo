# Agent Handover Protocol (TITANIUM Grade)

> **Goal**: Zero-Loss Context Transfer
> **Status**: **IMMUTABLE**

## 1. The Principle of "Perfect Memory"

An agent must assume the next agent knows **NOTHING**.
*   **Prohibited**: "See previous chat."
*   **Required**: explicit architectural state.

## 2. Handover Artifacts

When passing a task, you MUST generate a **Handover Record**:

```markdown
# Handover: [Task Name] -> [Next Agent]

## 1. Context Snapshot
- **Current State**: [Stable/Broken/WIP]
- **Last Action**: [Commited X / Ran Test Y]
- **Next Step**: [Verify Z]

## 2. Invisible Knowledge
- "Note: I locally modified X but reverted it because..."
- "Warning: FSEvents is flaky on the CI runner today."

## 3. The "Keys"
- PIDs of left-over processes.
- Temporary paths used.
```

## 3. The "Relay Race" Rule

*   **Agent A (Core)** passes to **Agent B (Edge)**:
    *   "The Happy Path works. Now break it."
*   **Agent B (Edge)** passes to **Agent C (Security)**:
    *   "I found these cracks. Now exploit them."
*   **Agent C (Security)** passes to **Architect**:
    *   "The system is verified. Sign off."

---
**Last Updated**: 2026-01-06
