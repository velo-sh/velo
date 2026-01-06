# Phase 6.2 Security Hardening Task Assignments

> **Role**: Rust Developer  
> **RFC**: [0012-full-armor-security-standard.md](../rfcs/0012-full-armor-security-standard.md)  
> **Parent Phase**: 6.1 (Cleanup/Sanitization)  
> **Status**: ASSIGNED (2026-01-06)

---

## 🛡️ Rust Developer Tasks: Surgical Shielding

### Task 1: Environment Surgical Refactor (P0)
- **File**: `src/serve/runner.rs`
- **Whitelist**: Keep `PATH`, `VIRTUAL_ENV`, `PYTHONUNBUFFERED`, `LANG`, `LC_ALL`, `TERM`, `TZ`.
- **Blacklist (CRITICAL)**: Block `PYTHONHOME`, `PYTHONPATH`, `LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`.

### Task 2: Randomized/Abstract Zygote Socket (P0)
- **Action**: 
    - Linux: Use **Abstract Namespace** (@velo-zygote-...).
    - macOS: Use `mkdtemp` (perm 700) and pass path via environment/pipe.
- **Crate**: Use `nix` for socket options.

### Task 3: Capability-Based Path Shield (P1)
- **Crate**: Implement via `cap-std`.
- **Action**: Use `cap_std::fs::Dir` for project root operations. Replace path strings with FD-based checks.

### Task 4: Environment Provenance Guard (SEC-ENV-001) [MANDATORY]
- **File**: `src/serve/runner.rs`
- **Action**: Implement auditing of whitelisted variable values.
- **Constraint**: Ensure `PATH` and `PYTHONPATH` entries are canonicalized and reside within `PROJECT_ROOT` or trusted system/venv prefixes.

### Task 5: FD Hygiene & Escape Protection (SEC-FS-002) [MANDATORY]
- **File**: `src/serve/runner.rs`
- **Prohibition**: Block access to `/proc/self/fd/`.

### Task 6: Zygote Peer Authentication (SEC-ZYG-003) [MANDATORY]
- **File**: `src/zygote/ipc.rs`
- **Action**: 
    - Linux: `SO_PEERCRED`.
    - macOS: `getpeereid` / `LOCAL_PEERCRED`.
    - Windows: Named Pipe Security Descriptors.
- **Crate**: Use `nix`.

---

## 🧪 Verification Tasks

| ID | Task | Target |
|----|------|--------|
| **V1** | Run `pytest tests/security/test_sec_shield.py` | 100% Pass |
| **V2** | Manual check: Run Velo in two projects simultaneously | No socket collision |
| **V3** | Manual check: Verify `velo serve` works in a `.venv` | No ModuleNotFoundError |

---

## Acceptance Criteria

- [ ] All "Three Sins" from the Whitebox Audit are addressed.
- [ ] No regression in functional suite (Zygote workers start).
- [ ] Environment provenance validated for whitelisted variables.
- [ ] FD hygiene enforced (only stdio inherited).
- [ ] Peer authentication verified (challenge-response handshake).
- [ ] Fail-Closed policy confirmed in all error paths.
