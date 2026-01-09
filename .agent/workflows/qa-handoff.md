---
description: Generate a precision handoff prompt for QA verification, ensuring context, changes, and verification criteria are explicit.
---

1. **Context Extraction**:
   - **Role**: Define the target agent role (e.g., QA, Security Auditor).
   - **Task**: clearly state the objective (e.g., Verify RFC-0014 Fixes).
   - **Context**: Summarize the "Before" state (regression/bug) and the "After" state.

2. **Change Cataloging**:
   - List **Key Changes** grouped by category:
     - **Performance**: Specific optimizations or logic changes.
     - **Security**: Feautres re-enabled or hardened.
     - **Hygiene/Cleanup**: Dead code removed, logs cleaned.
   - Cite specific file paths where possible.

3. **Verification Specification (Critical)**:
   - Provide **Exact Commands** to run (copy-pasteable).
   - Define **Success Criteria**:
     - **Quantitative**: e.g., "Latency < 600ms", "Speedup > 2x".
     - **Qualitative**: e.g., "No SecurityViolation errors".
   - Define **Scope**: Single package vs. Full regression.

4. **Output Generation**:
    Output a Markdown block using the following template:

    ```markdown
    **Role**: QA
    **Task**: [Task Name]
    **Context**: [Brief Situation Report]

    **Changes Implemented**:
    1.  **[Category]**: [Description of Change]
    2.  **[Category]**: [Description of Change]

    **Verification Plan (Required)**:
    1.  **[Test Name]**:
        Run: `[Command]`
        *   **Success Criteria**: [Metric/Condition]
    2.  **[Test Name]**:
        [...]

    **Artifacts**:
    *   [List updated files/docs]
    ```
