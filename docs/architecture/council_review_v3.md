# ⚖️ Council Review: V3 Isolation Architecture

**Subject**: V3 Transition Brief (Supervisor Model)
**Date**: 2026-01-28
**Verdict**: **APPROVED WITH HARDENING**

---

## 👥 The Council (Roll Call)

| Role | Persona | Focus Area |
| :--- | :--- | :--- |
| **Architect** | The Visionary | Structural Integrity & Goal Alignment |
| **Security Engineer** | The Paranoid | Isolation, Airlock, & Toxin Prevention |
| **Rust Core Dev** | The Systems Guy | Supervisor Performance & Safety |
| **Python Core Dev** | The Snake Charmer | Shim Compatibility & user-space mechanics |

---

## 🗣️ Phase II: The Critique (Transcript)

### 1. Vision Alignment
**Architect**: "The shift to a Supervisor Model is non-negotiable. We failed the 'Zero-Config' promise in V2 by forcing dependencies. Does V3's 'Runtime Injection' approach strictly adhere to the 'Thin Supervisor' philosophy?"

**Rust Core Dev**: "Yes. By removing `velo_zygote` deps from the runtime and making the Supervisor pure Rust, we align with the Android `system_server` model. The complexity moves to the Injection logic, but the architecture is cleaner."

### 2. The Security Audit (Airlock)
**Security Engineer**: "I'm looking at the **Airlock** protocol. You claim to 'Scrub' variables.
*   **Challenge**: What if the user sets `LD_PRELOAD`?
*   **Challenge**: What if the user sets `PYTHONPATH` in their shell before calling `velo`?
*   **Requirement**: The Airlock must be a **Whitelist** (Allow-List), not a Blacklist. You cannot just 'remove VELO_*'. You must rebuild the environment from scratch, keeping only `PATH` (sanitized), `TERM`, and `HOME`.
*   **Verdict**: **P0 Hardening Required**. The implementation of `enter_app_tier` must use `Command::env_clear()` followed by explicit reconstruction."

### 3. Shim Mechanics
**Python Core Dev**: "The `bootstrap.py` shim.
*   **Concern**: You say 'Zero Dependencies'. Does this include `typing`?
*   **Constraint**: It must run on Python 3.8+ (User's oldest supported version).
*   **Injection**: How do you inject it? Writing to `/tmp` is a race condition risk (TOCTOU).
*   **Suggestion**: Use `python -c` with the shim code passed as a string, or pipe via `stdin`. Avoid `/tmp` entirely if possible.
*   **Verdict**: **Approved**, but implementation must avoid disk I/O for the shim."

### 4. Supervisor Safety
**Rust Core Dev**: "The `ZygoteLauncher` refactor.
*   **Risk**: Detect Python (`detect_python`) might be slow (subprocess calls).
*   **Requirement**: Ensure this detection happens *before* the critical path or is cached.
*   **Verdict**: **Approved**."

---

## 📝 Phase III: The Verdict (Summary)

The Council **APPROVES** the Architecture V3 Transition (`v3_transition_brief.md`), subject to the following **P0 Hardening Directives**:

### 🛡️ Hardening Directives (Must Verify)
1.  **SEC-001 (Airlock)**: `Airlock::enter_app_tier` MUST use an **Allow-List** approach (Clear & Rebuild), not a Block-List approach.
2.  **SEC-002 (Shim)**: `bootstrap.py` injection MUST prioritize `python -c` or `stdin` over `/tmp` file creation to prevent TOCTOU attacks.
3.  **COMPAT-001**: `bootstrap.py` MUST be syntax-compatible with Python 3.8.

### 🏁 Final Status
**READY FOR IMPLEMENTATION**.
The Developer Agent is authorized to proceed, provided they adhere to the Security directives above.
