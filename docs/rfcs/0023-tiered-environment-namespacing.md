# RFC-0023: Tiered Environment Namespacing (Environment Sovereignty)

**Status**: DRAFT (Proposed for Phase 7.2 Hardening)
**Author**: Architect
**Date**: 2026-01-14

## 1. Summary
This RFC proposes a fundamental restructuring of how Velo handles environment variables to achieve "Environment Sovereignty." By moving from a flat `VELO_` prefix to a tiered namespace and implementing "Ghost Mode" shadowing for critical library paths, we ensure a clean, secure, and predictable boundary between the Velo Supervisor, the Zygote, and the User Worker processes.

## 2. Motivation
Currently, Velo uses a mix of environment variables for both internal coordination and user configuration, all loosely prefixed with `VELO_`. This leads to several issues:
1.  **Ambiguity**: It is unclear which variables are intended for internal infrastructure (`Supervisor <-> Zygote`) and which are for user configuration.
2.  **Information Leakage**: Internal metadata (e.g., `VELO_SYS_SOCK_FD`) may accidentally be visible to user application code within the Worker.
3.  **Environment Pollution**: Global environment variables like `PYTHONPATH` can interfere with Velo's internal module resolution, leading to "Binary Shadowing" or import errors.
4.  **Security Gaps**: The current whitelist approach is permissive by default for everything starting with `VELO_`.

## 3. High-Level Blueprint: The Three-Tier Namespace

We introduce a mandatory tiered naming convention for all variables within the Velo ecosystem:

### 3.1 `VELO_SYS_*` (System-Level)
*   **Purpose**: Low-level communication between Rust Supervisor and Zygote (e.g., `VELO_SYS_HOST_PID`, `VELO_SYS_SOCK_FD`, `VELO_SYS_AUTH_TOKEN`).
*   **Lifecycle**: Managed entirely by the Rust core.
*   **Security**: **Hard Scrubbing**. These variables MUST be forcibly stripped from the environment before a Worker process starts executing user code. The Worker should have no knowledge of the internal mechanical state of the supervisor.

### 3.2 `VELO_CONF_*` (Configuration-Level)
*   **Purpose**: User-tunable parameters that adjust Velo's behavior (e.g., `VELO_CONF_PORT`, `VELO_CONF_WORKERS`, `VELO_CONF_PRELOAD`).
*   **SSOT**: These should primarily be defined in `pyproject.toml` under `[tool.velo]`. Environment variables serve as high-priority overrides.
*   **Visibility**: Visible to the Zygote but should be read-only for the Worker.

### 3.3 `VELO_APP_*` (Application-Level)
*   **Purpose**: Reserved exclusively for user application logic (e.g., `VELO_APP_DB_URL`, `VELO_APP_SECRET_KEY`).
*   **Guarantee**: Velo guarantees that these variables will penetrate the **Environment Shield** and will never be used or modified by Velo internal logic.

### 3.4 Tier 4: `VELO_RUNTIME_*` (Read-only/Sealed)
*   **Purpose**: Immutable facts provided by the Velo engine to the application (e.g., `VELO_RUNTIME_WORKER_ID`, `VELO_RUNTIME_START_TIME`, `VELO_RUNTIME_MEM_LIMIT`).
*   **Behavior**: These are injected into the Python `sys.modules['velo'].env` rather than the OS environment, making them "un-spoofable" and protected from `os.environ.clear()` or manual tampering by user code.

---

## 4. Environment "Ghost Mode" (Shadowing)

To protect Velo's internal dependencies from user environment interference (and vice versa), we adopt a "Shadowing" strategy for critical shared facts like `PYTHONPATH` and `LD_LIBRARY_PATH`.

### 4.1 Injection Phase
During Rust startup, Velo identifies its internal library requirements and injects them into an internal-only variable: `VELO_INTERNAL_LIB_PATH`.

### 4.2 Synthesis Phase
At the moment of `fork()` (for Workers), the Rust Supervisor (or Zygote) synthesizes a fresh `PYTHONPATH` in memory:
```bash
PYTHONPATH = ${VELO_INTERNAL_LIB_PATH} + ":" + ${USER_DEFINED_PYTHONPATH}
```
This ensures that `velo_zygote` and related modules are always resolved correctly, regardless of how the user has configured their Shell environment.

---

## 5. Advanced Architect Patterns

### 5.1 Environment Provenance (Traceability)
To solve "Where did this variable come from?" madness, Velo will implement a **Provenance Audit**. On startup with `--debug`, Velo will log the source of every `VELO_` variable:
- `[SHELL]` -> Inherited from parent shell.
- `[DOTENV]` -> Loaded from `.env`.
- `[TOML]` -> Loaded from `pyproject.toml`.
- `[INTERNAL]` -> Synthesized by Velo Supervisor.

### 5.2 Rust-Side Schema Validation
Infrastructure variables (`VELO_CONF_*`) will be validated on the **Rust side** before the Zygote fork.
- **Example**: If `VELO_CONF_PORT` is set to "ABC", Velo will fail-fast with a TITANIUM error in the Supervisor, rather than letting the Python worker crash with a cryptic `ValueError` later.

### 5.3 Poisoning Protection (Environment Sealing)
Once the Worker has completed its bootstrap, Velo will optionally support "Sealing" the environment (`prctl(PR_SET_DUMPABLE, 0)` equivalent or simply freezing the `os.environ` proxy in Python) to prevent third-party middleware from poisoning the runtime environment during the request lifecycle.

---

## 6. "Default-Deny" Enforcement (The Shield)

Starting in Phase 7.2, the **Environment Shield** shifts from a permissive whitelist to a strict "Default-Deny" policy:

1.  **Minimal Whitelist**: `security_env_whitelist` in `config/constants.toml` is reduced to absolute essentials (`PATH`, `PWD`, `HOME`).
2.  **Automatic Rejection**: Any variable not in the minimal whitelist AND not starting with `VELO_APP_` is blocked by default.
3.  **Metatada Privacy**: All `VELO_SYS_` variables are explicitly intercepted and scrubbed before the Worker's entry point.

---

## 6. `pyproject.toml` as SSOT

Velo will proactively guide users away from defining infrastructure facts in Shell/Docker environments.
*   **Philosophy**: Environment variables are volatile and unordered; configuration files are controlled, versioned, and auditable.
*   **Action**: Update CLI warnings to suggest moving `VELO_CONF_*` exports into the `pyproject.toml` [tool.velo] block.

---

## 7. Implementation Invariants (Grand Council Requirements)

*   **INV-ENV-001 (Late Scrubbing)**: `VELO_SYS_*` variables MUST be scrubbed as late as possible (e.g., in the `pre_exec` hook of the Rust supervisor or the custom C entry point) to minimize the window for TOCTOU leaks.
*   **INV-ENV-002 (Early Injection)**: `VELO_RUNTIME_*` injection into `sys.modules['velo'].env` MUST occur before `sitecustomize.py`, `site.py`, or any user-defined modules are loaded.
*   **INV-ENV-003**: `VELO_APP_*` variables MUST NOT be modified or logged by the Velo binary.

---

## 8. Implementation Roadmap: Variable Sovereignty Cleanup

| Step | Action | Target |
|:---|:---|:---|
| 1 | **Rename Infra** | Rename internal coordination variables to `VELO_SYS_`. |
| 2 | **Hard Scrubbing** | Implement `strip_prefix("VELO_SYS_")` in `src/serve/worker.rs`. |
| 3 | **Ghost Mode** | Implement `PYTHONPATH` synthesis in the Zygote fork handler. |
| 4 | **Whitelist Tightening** | Update `config/constants.toml` to remove non-essential `VELO_` variables. |

## 8. Security Invariants
*   **INV-ENV-001**: No `VELO_SYS_*` variable shall exist in the Worker's `environ` after `app` initialization.
*   **INV-ENV-002**: `VELO_APP_*` variables MUST NOT be modified or logged by the Velo binary.
