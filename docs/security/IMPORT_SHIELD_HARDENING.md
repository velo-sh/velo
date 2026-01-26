# Velo Import Shield Hardening & Post-Mortem (Jan 2026)

## 1. Post-Mortem: The "Sin of Collision" Bypass (SEC-2026-001)

### Incident Summary
On Jan 26, 2026, during the "Sin of Collision" attack suite verification (`test_active_defense_bypass`), it was discovered that the **Active Import Shield** could be bypassed via a `sys.path` injection. An attacker (User App) could successfully import internal Velo runtime modules (e.g., `utils`, `bootstrap`) as Top-Level modules by manually pointing `sys.path` to the `velo_zygote` directory.

### Root Cause Analysis
The vulnerability resided in `velo_zygote/v_shield.py`. The `VeloRuntimeShield.find_spec` method implemented a defensive `try/except ImportError` block that was too broad. 

```python
# ATTACK VECTOR: Exception Swallowing
try:
    # ... resolution logic ...
    if spec_resolves_to_runtime:
        raise ImportError("Blocked")  # Shield signals a block
except ImportError:
    pass # <-- The shield accidentally swallowed its own block signal!
```

Because `find_spec` returned `None` (passing the responsibility to the next finder) instead of propagating the `ImportError`, the standard Python `PathFinder` would eventually find the module via the injected `sys.path` and load it.

### Remediation
The exception handling was refactored to ensure that `ImportError` strictly originating from the shield is propagated, while only expected failures in a "look-ahead" `PathFinder.find_spec` call are handled.

---

## 2. Security Hardening Roadmap (Tiered Defense)

To ensure the "Reset Gate" remains clean and impenetrable, Velo follows a tiered hardening strategy from application logic to binary enforcement.

### Tier 1: Application Layer (Short-Term / Completed)
*   **[DONE] Exception Isolation**: Ensure security violations are not catchable by standard `except Exception` blocks (using specific error types).
*   **[DONE] Path Scrubbing**: Automatically remove `velo_zygote` from `sys.path` immediately after Zygote pre-warming is complete.
*   **[DONE] Canonical Origin Check**: Use `os.path.realpath` to resolve symlink-based bypass attempts during origin validation.

### Tier 2: Runtime Environment (Mid-Term)
*   **Meta-Path Locking**: Wrap `sys.meta_path` to prevent the Shield from being removed or pivoted by user code.
*   **Namespace Mangling**: Use build-time obfuscation for internal Velo filenames (e.g., `utils.py` -> `__v_8f2a_utils.py`) to reduce the surface area for "Collision" attacks.
*   **SysPath Fingerprinting**: Monitor `sys.path` for unauthorized mutations involving sensitive system directories; trigger immediate process termination if detected.

### Tier 3: Native Enforcement (Long-Term)
*   **Rust Guard (PyO3)**: Re-implement the `VeloRuntimeShield` in Rust.
    *   **Why**: Move the security logic outside the mutable Python memory space.
    *   **Goal**: Ensure that even a compromised Python interpreter cannot disable the shield without corrupting its own process image.

### Tier 4: Architectural Sovereignty (Vision)
*   **FD-Based Loading (Physical 脱钩)**: Transition the Velo loader to use **File Descriptors (FD)** rather than file paths for internal modules.
    *   **Mechanism**: The supervisor opens the FD and passes it to the Python guest.
    *   **Security**: Internal modules never exist as "addressable files" in the Guest's path-based filesystem, making them physically invisible to the App.

---
**Status**: 🟢 ACTIVE TRACKING
**Last Updated**: 2026-01-26
**Tests**: `tests/qa/heavy/chaos/test_sin_of_collision.py` (Mandatory regression gate)
