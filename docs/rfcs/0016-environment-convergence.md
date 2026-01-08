# RFC-0016: Environment Convergence & Test Hygiene

**Status**: DRAFT
**Owner**: DevOps/Architecture Team
**Created**: 2026-01-07

## 1. Problem Statement
The current Velo codebase exhibits "Environment Fragmentation":
*   **Socket Path Logic**: Duplicated and divergent between `src/zygote/ipc.rs`, `velo_zygote/main.py`, `tests/qa/conftest.py`, and `tests/qa/phase_6_1_1/conftest.py`.
*   **Permission Enforcement**: Inconsistent (0700 vs 0755) depending on whether Velo is run by a user, CI runner, or test harness.
*   **Isolation**: Tests rely on shared system paths (`/tmp`, `/var/folders`), leading to "Zygote Pollution" and race conditions (e.g., `test_SEC_605`).

## 2. The Solution: "Hermetic Test Environments"

We propose strictly enforcing that **NO Test** shall verify behavior against the host system's default paths (`/tmp`, `/var/run`). Instead, every test must run in a hermetically sealed `TestEnvironment`.

### 2.1 The `VeloTestEnv` Fixture
A new, centralized fixture (replacing `isolated_env`) that forces all environment variables to a private directory:

```python
class VeloTestEnv:
    def __init__(self, root: Path):
        self.root = root
        self.tmp = root / "tmp"
        self.home = root / "home"
        self.xdg = root / "run"
        
        # KEY: We dictate the universe
        self.env = {
            "TMPDIR": str(self.tmp),
            "TEMP": str(self.tmp),
            "HOME": str(self.home),
            "XDG_RUNTIME_DIR": str(self.xdg),
            "VELO_ZYGOTE_SOCKET": "" # Force default logic or set explicitly
        }
```

### 2.2 Shared Configuration Logic
Instead of `conftest.py` guessing paths, we should export a "Velo Standard Paths" specification or utility that both the Rust binary and Python tests consume (or strictly adhere to).

**Standard**:
*   **Socket**: `XDG_RUNTIME_DIR/velo/zygote.sock` (Primary) -> `TMPDIR/velo-{uid}/` (Fallback).
*   **Permissions**: STRICT `0700` for the directory. `0600` for the socket.

## 3. Implementation Plan
1.  **Consolidate Fixtures**: Merge `tests/qa/phase_6_1_1/conftest.py` into `tests/qa/conftest.py` or `tests/qa/fixtures/`.
2.  **Enforce Hermeticity**: Update `conftest.py` to auto-inject `VeloTestEnv` into the environment of *every* `subprocess.run` call via the existing monkey-patch or a new wrapper.
3.  **Rust/Python Parity**: Create a shared spec (json or simple .rs/.py lib) for path resolution to ensure `src/zygote/ipc.rs` and `velo_zygote/main.py` never diverge.

## 4. Best Practices for Future Compexity
*   **Never Trust `/tmp`**: It is a shared, hostile resource.
*   **Fail Fast on Env Leaks**: Tests should fail if they detect write access to `/tmp` outside their sandbox.
*   **Dynamic Timeouts**: Continue using `TIMEOUT_MULTIPLIER` but centralize it in a `Timeouts` struct available to Rust tests too.
