# Phase 6.2 Security Hardening Task Assignments

> **Role**: Rust Developer  
> **RFC**: [0012-full-armor-security-standard.md](../rfcs/0012-full-armor-security-standard.md)  
> **Parent Phase**: 6.1 (Cleanup/Sanitization)  
> **Status**: ASSIGNED (2026-01-06)

---

## 🛡️ Rust Developer Tasks: Surgical Shielding

### Task 1: Environment Surgical Refactor (P0)
- **File**: `src/serve/runner.rs`
- **Action**: Remove `env_clear()`. Use `env_remove()` for a targeted blacklist.
- **Whitelist**: Ensure the following survive: `PATH`, `VIRTUAL_ENV`, `PYTHONUNBUFFERED`, `LANG`, `LC_ALL`, `TERM`.
- **Constraint**: Strictly block `PYTHONPATH` and `LD_PRELOAD`.

### Task 2: Unique Zygote Identity (P0)
- **File**: `src/zygote/ipc.rs`
- **Action**: Implement SHA256 hashing of the canonical project path for the Unix socket filename.
- **Hardening (Expert)**: Use `O_EXCL` on bind and `chmod 600` on the socket file.

### Task 3: Path Shield Implementation (P1)
- **File**: `src/serve/sandbox.rs` [NEW]
- **Action**: Implement a `validate_path(target, root)` utility that uses `fs::canonicalize` on both inputs to prevent symlink escape.
- **Integration**: Apply this check to all file operations in the worker loop.

### Task 4: Environment Provenance Guard (SEC-ENV-001) [MANDATORY]
- **File**: `src/serve/runner.rs`
- **Action**: Validate whitelisted variables (`PATH`, `PYTHONPATH`).
- **Logic**: Every path entry must be canonicalized and checked against `PROJECT_ROOT` or trusted system prefixes. Reject startup if a mismatch is found.

### Task 5: FD Hygiene & Escape Protection (SEC-FS-002) [MANDATORY]
- **File**: `src/serve/runner.rs`
- **Action**: Implement `close_fds_on_exec`. Ensure workers start with exactly 3 FDs (0, 1, 2).
- **Prohibition**: Block access to `/proc/self/fd/`.

### Task 6: Zygote Peer Authentication (SEC-ZYG-003) [MANDATORY]
- **File**: `src/zygote/ipc.rs`
- **Action**: 
    - Linux: Implement `SO_PEERCRED` UID verification.
    - Cross-Platform: Implement the **Nonce-HMAC Challenge Handshake** protocol.

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
- [ ] Security Expert recommendations (O_EXCL, Canonicalization) fully integrated.
