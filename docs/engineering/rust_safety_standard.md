# Rust Safety Standard (TITANIUM Grade)

> **Authority**: Rust Core Dev / Architect
> **Status**: **IMMUTABLE**

## 1. The `unsafe` Policy

**Principle**: "Unsafe is Guilty until Proven Innocent."

*   **Zero Unsafe in Business Logic**: `unsafe` blocks are PROHIBITED in `src/serve`, `src/cmd`, or `src/graph`.
*   **Encapsulation**: `unsafe` is only allowed in `src/os` or `src/shim` modules, and MUST be wrapped in a safe abstraction.
*   **Justification**: Every `unsafe` block MUST be preceded by a `// SECURITY: ...` comment explaining why it is safe.

## 2. RAII & Resource Management

**Principle**: "Drop is the only Cleanup."

*   **ManagedChild**: All subprocesses MUST be wrapped in `ManagedChild` (or equivalent) to ensure `kill(PID_GROUP)` on drop.
*   **File Descriptors**: Raw FDs (`RawFd`) are forbidden. Use `OwnedFd` or `File`.
*   **Locks**: No manual `mutex.unlock()`. Use scope-based locking.

## 3. Error Handling (Titanium)

**Principle**: "Errors are diagnosable telemetry."

*   **Context**: Use `color_eyre` or `anyhow` with `.context("Action failed")`.
*   **No Panic**: `unwrap()` and `expect()` are FORBIDDEN in production code paths.
*   **Exit Codes**: CLI must return distinct exit codes (see `sysexits.h` style) for distinct failure modes.

## 4. Async Runtime

**Principle**: "Tokio is the Operating System."

*   **Blocking**: No blocking I/O (`std::fs`) in async context. Use `tokio::fs`.
*   **Spawning**: Use `tokio::spawn` with `JoinHandle` management. Orphan tasks are leaks.
*   **Signals**: Use `tokio::signal` exclusively.

---

**Last Updated**: 2026-01-06
