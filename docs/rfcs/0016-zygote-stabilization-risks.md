# RFC-0016: Zygote Stabilization Known Issues and Mitigations

**Date**: 2026-01-08
**Status**: Accepted
**Related Commit**: `3ba3cdd` (fix(zygote): stabilize worker lifecycle and restore 150x speedup on macOS)

## Context

The Zygote stabilization effort introduced several architectural changes to achieve TITANIUM-grade isolation and a 151x performance speedup on macOS. This document captures the known risks, trade-offs, and recommended mitigations for each change.

---

## Risk Assessment Matrix

| Change | Risk Level | Primary Concern | Status |
|--------|:----------:|-----------------|--------|
| Uvicorn Signal Handling | 🟢 Low | API Changes | Monitor |
| `os.setsid()` Isolation | 🟢 Low | Debugging UX | Acceptable |
| Reaper Disabled (SSOT) | 🟡 Medium | Orphan Processes on Supervisor Crash | Action Needed |
| macOS Sandbox | 🟡 Medium | Apple Deprecation Risk | Action Needed |
| Binary Path Override | 🟢 Low | CI Path Variance | Acceptable |

---

## 1. Uvicorn Signal Handling

### Change
Workers no longer have direct control over their signal handlers. The Rust supervisor sends `SIGTERM` and waits for a clean exit via the `WaitWorker` IPC.

### Risk: API Compatibility
- **Concern**: Uvicorn may change its signal handling internals in future versions.
- **Mitigation**: We rely on the standard POSIX `SIGTERM` response, not uvicorn-specific APIs. Uvicorn's graceful shutdown is triggered by its asyncio loop upon receiving `SIGTERM`, which is independent of who installs the handler.
- **Action**: Pin uvicorn version in `pyproject.toml` and monitor its CHANGELOG for breaking changes.

### Risk: Graceful Shutdown Bypass
- **Concern**: Bypassing uvicorn's signal installer might skip its internal request-draining logic.
- **Mitigation**: Testing confirms that uvicorn still performs graceful shutdown when sent `SIGTERM`. The `WaitWorker` IPC provides a synchronous wait, ensuring complete exit.

---

## 2. Process Group Isolation (`os.setsid()`)

### Change
Forked workers immediately call `os.setsid()` to create a new session and process group.

### Risk: Reduced Debuggability
- **Concern**: `strace -p <parent_pid>` or `kill -SIGINT <parent_pid>` will not affect child workers.
- **Mitigation**: This is intentional. Use `ps -o sid,pid,pgid,cmd` to discover worker PIDs. `strace -f` can also follow forks.

### Risk: Terminal Signal Leak
- **Concern**: `Ctrl+C` in the terminal will not gracefully stop workers.
- **Mitigation**: This is by design. The Rust supervisor is the Single Source of Truth (SSOT) for lifecycle management. Users should use `velo serve --stop` or send `SIGTERM` to the main process.

---

## 3. Disabled Zygote Reaper (SSOT Transfer)

### Change
The Python Zygote no longer calls `kill_all()` or `reap_stale()`. All worker termination is delegated to the Rust supervisor.

### Risk: Orphan Processes on Supervisor Crash
- **Concern**: If the Rust supervisor is killed by `SIGKILL`, it cannot send `Shutdown` to the Zygote. Workers may remain as orphans.
- **Current State**:
    - **Linux**: `PR_SET_PDEATHSIG(SIGTERM)` is set, so children auto-terminate when the parent dies.
    - **macOS**: No equivalent kernel mechanism. Children may orphan.
- **Recommended Action**:
    1. Implement a **Heartbeat Watchdog** in the Zygote: if no IPC message is received from the supervisor within N seconds, initiate a self-destruct sequence.
    2. Document that users on macOS should use `pkill -f velo` for emergency cleanup.

> [!WARNING]
> This is the highest-priority risk item. Recommend addressing in the next release cycle.

---

## 4. macOS Sandbox (`sandbox-exec`)

### Change
The Zygote process on macOS is launched inside a kernel sandbox with a restrictive profile.

### Risk: Overly Restrictive Rules
- **Concern**: User applications may require file I/O, network access, or other syscalls denied by the profile.
- **Current Profile**: Uses `(allow default)` as a base, which is permissive. Explicit denies are minimal.
- **Mitigation**: If users encounter `sandboxd` denials, they can inspect `/var/log/system.log` for specific deny events. The profile can be expanded as needed.
- **Recommended Action**: Add an environment variable `VELO_SANDBOX_ENABLED=false` to allow users to disable the sandbox if needed.

### Risk: Apple Deprecation
- **Concern**: Apple does not officially document or support `sandbox-exec` for third-party developers. It may be removed in a future macOS release.
- **Mitigation**: The sandbox is a defense-in-depth layer, not a primary security control. If deprecated, the code can gracefully fall back to non-sandboxed execution (as it currently does on Linux).
- **Recommended Action**: Create a `#[cfg(target_os = "macos")]` fallback path that skips sandboxing if the `sandbox-exec` binary is not found.

---

## 5. Binary Path Override (Test Harness)

### Change
The `velo_binary` pytest fixture now returns an absolute path to `target/debug/velo`, forcing tests to use the locally compiled binary.

### Risk: CI Path Mismatch
- **Concern**: CI environments with different directory structures might not find the binary.
- **Mitigation**: The path is computed relative to the test file (`__file__`), making it portable.
- **Recommended Action**: None. This is a test-only change with no production impact.

---

## Future Work (Prioritized)

1. **[P0] Heartbeat Watchdog**: Implement a timeout-based reaper in the Zygote to handle supervisor death on macOS.
2. **[P1] Sandbox Disable Flag**: Add `VELO_SANDBOX_ENABLED` environment variable.
3. **[P2] Uvicorn Version Pinning**: Audit and pin uvicorn version in `pyproject.toml`.
4. **[P3] `sandbox-exec` Fallback**: Implement graceful degradation if sandboxing fails.

---

## Appendix: Trap Catalog

This stabilization effort discovered and patched the following architectural traps:

| Trap ID | Name | Symptom | Resolution |
|---------|------|---------|------------|
| 162 | Shadow Binary | Tests passed locally but failed in CI with different behavior | Standardized `velo_binary` fixture path |
| 152 | Dual Ownership | Workers killed by both Zygote reaper and Supervisor | Deactivated Zygote reaper |
| 165 | Uvicorn Signal Hijacking | `SIGTERM` caused double-exit or no-exit on macOS | Delegated signal handling to Supervisor |
| 158 | Signal Reset Race | Signals inherited from parent caused Ghost Exits | Implemented Signal Masking Ritual |
| 163 | macOS Sandbox Conflict | Sandbox denied critical syscalls on older profiles | Updated profile to `(allow default)` |
