# Python Integration Standard (TITANIUM Grade)

> **Authority**: Python Core Dev / Architect
> **Status**: **IMMUTABLE**

## 1. The Runtime Boundary

**Principle**: "Rust owns the Process; Python rents the Thread."

*   **Lifecycle**: Rust `main()` starts first, setups signals, then initializes Python.
*   **Signals**: Python signal handlers are masked/reset. Rust `ctrlc` handler owns `SIGINT`.
*   **GIL**: Minimized. All I/O should happen in Rust (no-GIL) before handing data to Python.

## 2. Zygote Safety (Fork)

**Principle**: "Fork is Dangerous."

*   **Pre-Fork Hygiene**: All FDs > 2 MUST be closed (`close_range`).
*   **Randomization**: ASLR and Hash Seeds must be re-initialized post-fork (if possible) or managed via `EnvironmentShield`.
*   **Threads**: Zygote MUST be single-threaded before fork.

## 3. ABI & Interop

**Principle**: "ABI is a moving target."

*   **PyO3**: Use strictly versioned `pyo3` bindings.
*   **Stable ABI**: Prefer Stable ABI (`abi3`) where performance allows.
*   **Conversion**: Use `IntoPy` / `FromPy` traits. No raw pointer casting.

## 4. Environment Management

**Principle**: "The Environment is Hostile."

*   **Surgical Shielding**: Whitelist-only environment variables (RFC-0012).
*   **VirtualEnv**: Auto-detection via `VIRTUAL_ENV` or `pyvenv.cfg`.
*   **Path Safety**: Never blindly trust `sys.path`.

---

**Last Updated**: 2026-01-06
