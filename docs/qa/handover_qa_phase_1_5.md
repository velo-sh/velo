# QA Handoff: Python SSOT & Debugging Mission (Titanium Grade)

**Priority:** P0 (Blocking Release)
**Branch:** `refactor/python-ssot`
**Target:** `main` (Post-Review)

## 1. Mission Overview
This mission unified the configuration source of truth (SSOT) between Rust and Python, hardened the Zygote boot process, and introduced automated forensics for CI failures.

**Key Changes:**
- **SSOT**: `constants.toml` -> `build.rs` -> `constants.py` (No more hardcoded magic strings).
- **Traceability**: `request_id` (UUIDv7) propagated via Environment & Headers.
- **Resilience**: `VELO_SHM` injection hotfix & Strict `mypy` typing.
- **Forensics**: Automated `velo bundle collect` on test failure.
- **Security**: `ImportShield` Audit Mode (`dry_run`).

---

## 2. Test Environments
All tests must pass in **Verification Level 3 (Hardened)**:
1.  **Local (macOS/Dev)**: Developer environment (Quick check).
2.  **Docker (Ubuntu/CI)**: Simulation of production environment (`scripts/local-ci.sh --docker`).
3.  **Strict NUMA**: `VELO_STRICT_NUMA=1` (Simulating HPC nodes).

---

## 3. Strict Test Matrix (Acceptance Criteria)

### A. Phase 1: Configuration SSOT (Zero-Drift)
- [ ] **Data Parity Test**:
    - Action: Dump `src/common/constants.rs` and `velo_zygote/constants.py` values at runtime.
    - Assertion: `diff` must be ZERO.
- [ ] **Type Safety**:
    - Action: Modify `constants.toml` string field to integer.
    - Assertion: Build **MUST FAIL** (Rust) or `mypy` **MUST FAIL** (Python).
- [ ] **Platform Isolation**:
    - Action: Run on Linux.
    - Assertion: `PATH_MACOS_*` constants must **NOT** be present or used in `constants.py`.

### B. Phase 2: Traceability (UUIDv7)
- [ ] **Header Propagation**:
    - Action: Send HTTP Request `X-Velo-Request-ID: <custom-uuid>`.
    - Assertion: Worker log line **MUST** contain `[req_id=<custom-uuid>]`.
- [ ] **Generation Order**:
    - Action: Concurrently generate 1000 requests.
    - Assertion: UUIDs must be time-ordered (k-sortable check).

### C. Phase 3: Zygote Stability (Hotfix Verification)
- [ ] **FD Passing Regression**:
    - Action: Start Zygote.
    - Assertion: `VELO_SHM` object **MUST** be present in `globals()` of worker process.
    - Assertion: Verify `shm_fd` is valid and not `-1`.
- [ ] **Socket Buffer Overflow**:
    - Action: Send payload = `MAX_MESSAGE_SIZE` (10MB).
    - Assertion: Zygote must reject/handle gracefully, **NOT CRASH**.

### D. Phase 4: Forensics (Failure Bundle)
- [ ] **Artifact Integrity**:
    - Action: Force a test failure.
    - Assertion: `failure-bundle-*.tar.gz` is created.
    - Assertion: Tarball contains `zygote.log`, `worker.log`, and `metadata.json`.
- [ ] **No Secrets Leak**:
    - Action: Set `VELO_SECRET_KEY=sensitivedata` in env.
    - Assertion: Grep tarball content. Secret **MUST NOT** be visible.

### E. Phase 5: ImportShield (Audit Mode)
- [ ] **Dry Run Non-Blocking**:
    - Action: Set `VELO_SHIELD_MODE=dry_run`.
    - Action: Worker imports `os` (or restricted module).
    - Assertion: Import **SUCCEEDS**.
    - Assertion: Log contains `[SECURITY AUDIT] ... ALLOWED by dry_run`.
- [ ] **Enforcement Blocking**:
    - Action: Set `VELO_SHIELD_MODE=enforce`.
    - Action: Worker imports `os`.
    - Assertion: Import **FAILS** (`ImportError`).

---

## 4. Performance Gates (Strict)
- [ ] **Bootstrap Overhead**: Zygote cold start < 50ms (SSOT resolution overhead check).
- [ ] **Request Latency**: P99 Overhead < 0.5ms (UUID generation cost).

## 5. Known Risks
- **Linux CI**: `ImportShield` collisions on `sitecustomize.py`. (Mitigation: Use `dry_run` for first week).
- **Update Drift**: If `config/constants.toml` is modified, `cargo build` **MUST** run before Python tests. Ensure CI pipeline enforces this order.

**Signed-off by:** Agent Antigravity (Dev)
