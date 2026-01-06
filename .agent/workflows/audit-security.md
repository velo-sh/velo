---
description: Perform a TITANIUM Security Audit (SOP-003 Tier 4 Check)
---

# 🛡️ Skill: Audit Security (Titanium Force)

> **Authority**: Master Security Standard
> **Trigger**: When `Security Specialist` is summoned or before Release.

## 1. 📚 Phase I: Load the Law

You cannot enforce what you don't know.

1.  **Read the Invariants**:
    - `view_file docs/security/master_security_standard.md`
    - `view_file docs/specialized/cryptography_standard.md`
    - `view_file docs/engineering/rust_safety_standard.md`

## 2. 🔍 Phase II: The Scan (Hostile Review)

Search for specific "Sins".

1.  **Sin of Unsafe**:
    - `grep_search "unsafe {"` (Must have `// SECURITY:` comment).
2.  **Sin of Cryptography**:
    - `grep_search "sha256"` (Should be BLAKE3, unless legacy).
    - `grep_search "md5"` (Forbidden).
3.  **Sin of Parsing**:
    - `grep_search "unwrap()"` (Forbidden in production).
    - `grep_search "expect()"` (Forbidden in production).

## 3. 🚨 Phase III: The Indictment

1.  **Report Findings**:
    - List every violation found.
    - Classify as **P0 (Blocker)** or **P1 (Warning)**.
2.  **Recommendation**:
    - If P0 exists: "RELEASE BLOCKED".
    - If Clean: "TITANIUM SEAL APPLIED".
