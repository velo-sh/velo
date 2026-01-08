---
description: Safely merge `main` into the current branch to resolve core conflicts, following a "Keep Both" preservation strategy with mandatory backups.
---

# Safe Merge & Core Conflict Resolution Protocol

Use this workflow when you need to update your feature branch with the latest changes from `main`, especially when significant core changes have occurred that conflict with your work.

## 1. Safety First (Backup)
Before doing anything, secure the current state.
```bash
# named with timestamp for uniqueness
git branch backup/pre-merge-$(date +%s)
```

## 2. Fetch Upstream
Ensure you have the absolute latest state of `main`.
```bash
git fetch origin main
```

## 3. Merge Attempt
Initiate the merge from the remote main.
```bash
git merge origin/main
```

## 4. Conflict Resolution Protocol (The "Keep Both" Rule)
If conflicts occur, you must adhere to the following logic:

1.  **Preserve Both**: The primary goal is to retain **both** the new core logic from `main` AND your feature changes.
    *   *Example*: If `main` adds a parameter to a function you modified, update your modification to include that parameter.
    *   *Example*: If `main` refactors a module you added code to, move your code into the new structure.

2.  **Stop & Ask (Escalation)**:
    *   If you encounter a conflict where "Keeping Both" is logically impossible (e.g., mutually exclusive architectural changes), or if you are simply unsure how to integrate them safely:
    *   **STOP**. Do not guess.
    *   Call `notify_user` with a clear summary of the conflict and ask for instructions.

3.  **Duplicate Fixes (Overlapping Logic)**:
    *   If both sides fix the same bug (e.g., both added a `nil` check):
        *   **Identical Code**: Keep one (merge logically).
        *   **Different Approaches**: This counts as "Unable to Keep Both". **STOP** and ask.

4.  **Verify**:
    *   After resolving, run `cargo check` and relevant tests to ensure the integration didn't break functionality.

## 5. Completion
Once conflicts are resolved and verified:
```bash
git add .
git commit -m "Merge origin/main - Resolve core conflicts"
```
