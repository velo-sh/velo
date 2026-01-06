# Council Review: RFC-0013 Kinetic Protocol

> **Authority**: SOP-001 / `/ask-council`
> **Subject**: RFC-0013 (Draft)
> **Date**: 2026-01-06 (Round 2)

## 1. The Summons

| Role | Focus | Check |
|:---|:---|:---|
| **Rust Core** | Safety | Does "Silent Fallback" actually prevent zombies? |
| **Python Core** | Preload | Is the PGO formatting standard? |
| **Security** | Isolation | Does `SO_PEERCRED` block cross-user attacks? |

## 2. The Critique (Round 2)

### 🦀 Rust Core Developer
> "Reviewing Section 3.1 (Silent Fallback).
> You defined a 10ms timeout.
> **Question**: Is this wall-clock time or CPU time?
> **Correction**: Must be `Duration::from_millis(10)` wall-clock on the socket read.
> **Verdict**: **APPROVED** (with strict timeout implementation)."

### 🐍 Python Core Developer
> "Reviewing Section 4 (PGO).
> You mention `kinetic_profile.json`.
> **Condition**: This file MUST be in the `.velo/` directory, not the project root, to avoid clutter.
> **Verdict**: **CONDITIONAL APPROVAL** (Move file to hidden dir)."

### 🛡️ Security Specialist
> "Reviewing Section 5 (Security).
> `SO_PEERCRED` is Linux-specific.
> **Gap**: What about macOS?
> **Requirement**: On macOS, you must use `getpeereid` or equivalent. If not available, fallback to `O_PATH` inode verification.
> **Verdict**: **CONDITIONAL APPROVAL** (Add macOS Check)."

## 3. The Verdict

**🟢 CONDITIONAL APPROVAL**

The design is sound, but requires 2 minor amendments before Coding:
1.  **Ops**: Store profile in `.velo/kinetic_profile.json`.
2.  **Sec**: Define macOS Peer Credential mechanism.

**Proceed to Implementation?**: **YES**, but include these fixes in the code.
