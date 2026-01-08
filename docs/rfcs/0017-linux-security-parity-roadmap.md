# RFC-0017: Linux Security Parity Roadmap (The "Security Debt" Record)

| Field | Value |
| :--- | :--- |
| **RFC ID** | 0017 |
| **Status** | Active (Debt Recorded) |
| **Created** | 2026-01-08 |
| **Dependencies** | [RFC-0012 (Full Armor)](./0012-full-armor-security-standard.md), [RFC-0016 (Env Convergence)](./0016-environment-convergence.md) |

## 1. Executive Summary

This document formally records the **Security Debt** incurred during the "Zygote Stabilization" phase (Jan 2026). While Velo achieved "TITANIUM" grade security on macOS (via `sandbox-exec` and `ImportShield`), the Linux implementation was temporarily degraded to resolve critical CI/CD blockers.

**Critical Deviation:** Linux environments currently lack `ImportShield` protection and Kernel-level Sandboxing, violating the "Platform Parity" principle of RFC-0012.

## 2. The Security Gap (Current Status)

| Security Feature | macOS (Reference) | Linux (Current) | Status | Risk Level |
| :--- | :--- | :--- | :--- | :--- |
| **ImportShield** | ✅ Active (Blocking) | ❌ **Disabled** | **DEGRADED** | **Medium**: Malicious dependencies can be imported during bootstrap. |
| **Kernel Sandbox** | ✅ `sandbox-exec` | ❌ **None** | **DEGRADED** | **High**: No OS-level file write prevention. |
| **Process Isolation** | ✅ `setsid()` | ✅ `setpgid()` | **Parity** | Low: Group isolation is sufficient for signal management. |
| **Signal Hygiene** | ✅ Clean Slate | ✅ Clean Slate | **Parity** | None. |
| **FD Hygiene** | ⚠️ Disabled (Stability) | ⚠️ Disabled (Stability) | **Parity** | Low: Both platforms vulnerable to FD leaks until re-enabled. |

## 3. Root Cause Analysis

The degradation was a conscious decision to unblock the release pipeline, driven by the following technical constraints:

1.  **CI Environment Instability**: AWS/GitHub Actions runners on Linux exhibited crashes when `ImportShield` interacted with `uvloop`/`asyncio` during startup. The exact conflict remains under investigation.
2.  **Lack of Linux Equivalents**: The macOS `sandbox-exec` wrapper has no direct, zero-dependency equivalent on Linux. Standard tools like `bubblewrap` or `firejail` are not guaranteed to be present in all user environments, and writing a raw `seccomp-bpf` filter in Python/Rust requires significant R&D.
3.  **Fast-Track Delivery**: The priority was correcting the "Zombie Process" and "Signal Race" defects (RFC-0016 context), necessitating a temporary compromise on depth-defense features.

## 4. Remediation Plan

We adopt a **Fail-Open** strategy for now (warn but proceed), moving towards **Fail-Closed** (refuse to start) as parity is restored.

### Phase 1: Acknowledge & Warn (Immediate)
- [x] **SSOT Update**: Created this RFC to track the debt.
- [x] **Code Comments**: Explicitly marked disabled blocks in `main.py` with `(Linux CI Stability: Disabled temporarily)`.

### Phase 2: Investigation & Parity (Next Release)
- [ ] **Debug ImportShield on Linux**: Isolate the crash. Is it `sys.meta_path` conflict? Is it a race condition?
    - Action: Create a minimal reproduction script for Linux docker containers.
- [ ] **Research Linux Sandbox**: Evaluate `landlock` (kernel 5.13+) vs `bubblewrap`.
    - Preference: `landlock` (Rust native support via crate) > `bubblewrap` (external binary).

### Phase 3: Architectural Uniformity (Future)
- [ ] **Abstract Security Provider**: Refactor `main.py` to use a strategy pattern.
    ```python
    class SecurityProvider(Protocol):
        def install_import_guard(self) -> None: ...
        def enter_sandbox(self) -> None: ...
    ```
- [ ] **Strict Mode**: Introduce `VELO_STRICT_SECURITY=1` env var.
    - If set, Velo MUST panic if sandboxing or ImportShield cannot be active.

## 5. Governance

This debt MUST be reviewed in every subsequent "Grand Council" meeting until resolved. It serves as a blocking item for the "Velo v1.0 General Availability" milestone.
