# V3 Transition Brief: The Supervisor Architecture

**Subject**: Migration from "Heavy Runtime" to "Zero-Config Supervisor"
**Role**: Architect Handoff
**Target Audience**: Developer Agents / Implementation Team

---

## 1. The Critical Problem (Why we are doing this)

The current Velo architecture suffers from **Runtime Injection** and **Dependency Hell**.

*   **Runtime Injection**: Velo currently forces its own internal Python environment (Domain A) into the User's Process (Domain B).
    *   *Result*: User code runs inside Velo's environment, not its own `.venv`.
    *   *Symptom*: Users cannot use `pydantic < 2.0` because Velo forces `pydantic 2.8`.
*   **Dependency Pollution**: To fix the above, we required users to install `velo` as a dependency.
    *   *Result*: "Zero-Config" promise is broken. Users must modify `pyproject.toml`.

**Conclusion**: The current Model (Runtime as a Dependency) is **fundamentally flawed**.

---

## 2. The Current State (Gap Analysis)

| Feature | Current Implementation (Legacy/V2) | Architecture Violation |
| :--- | :--- | :--- |
| **Zygote Launch** | `Command::new("python").env("PYTHONPATH", VELO_LIB)` | **Pollution**: Injects Velo's internal libs into User space. |
| **Zygote Identity** | A "Universal Zygote" owned by Velo. | **Sovereignty Breach**: Zygote should belong to the User Project. |
| **Velo Code** | `velo_zygote` is a heavy library (45KB+) using `fastapi`/`uvicorn`. | **Fatality**: Requires Velo's deps to run. Cannot run in a raw user venv. |
| **Environment** | Mixed. Velo vars (`VELO_*`) leak into Zygote. | **Toxicity**: Breaks user tools that rely on clean env. |

---

## 3. The Target Solution (Architecture V3)

We shift to the **Supervisor Model** (similar to Android's `system_server` managing Zygotes, or `containerd` managing containers).

### 3.1 The Supervisor (Rust)
*   **Role**: Manager ONLY.
*   **Physics**: A pure binary. **NO** Python dependencies involved in its own execution.
*   **Responsibility**: Locate User Python -> Scrub Environment -> Inject Shim.
*   **Process Physics**:
    *   **Toxin Origin**: When Supervisor spawns a child, it defaults to inheriting the Supervisor's environment (`VELO_CONFIG`, etc). This is why the **Airlock** is mandatory.
    *   **Velo Physics**: Velo is a **standalone Rust binary** (like `uv`). It does **NOT** require a virtualenv to run itself. It has **Zero** Python dependencies for its own process.
    *   **Python Source**: The supervisor MUST use the **User Project's Virtualenv Python** (`.venv/bin/python`). It MUST NEVER use the System Python (`/usr/bin/python`). If `.venv` is missing, Supervisor calls `integrated_uv_bin` to create it.
    *   **UV Physics**: `uv` is a standalone Rust binary. It does **NOT** require a virtualenv to run. It does **NOT** need to maintain a "Velo Internal Venv". It operates directly on the User's Venv.

### 3.2 The Project Zygote (Python)
*   **Role**: The Worker Factory.
*   **Identity**: Runs **100%** in the User's Virtualenv (`.venv`).
*   **Physics**: Does **NOT** have `velo` installed in `site-packages`.
*   **Capability**: Gained via **Runtime Injection** of a "Thin Shim".

### 3.3 The Isolation Protocol ("Airlock")
Before spawning the Zygote, the Supervisor MUST perform a strict **Allow-List Reconstruction** (SEC-001):
1.  **Purge**: `Command::env_clear()`.
2.  **Reconstruct**: Explicitly set ONLY safe variables:
    *   `PATH` (Sanitized system path).
    *   `HOME` (User home).
    *   `TERM`, `LANG`, etc.
    *   `VIRTUAL_ENV` (User's .venv).
3.  **Forbidden**: Do NOT just "unset" Velo variables. Deep cleaning is required to prevent `LD_PRELOAD` or other environmental toxins.

---

## 4. Developer Directives (Implementation Guide)

### Directive 1: The "Thin Shim" (`bootstrap.py`)
Create a new file `src/zygote/bootstrap.py`.
*   **Constraint**: **Zero Dependencies**. Use `socket`, `struct`, `os`, `sys`, `importlib` ONLY.
*   **Compatibility**: Must be compatible with **Python 3.8+** (COMPAT-001).
*   **Function**:
    1.  Connect to Supervisor Socket (FD passed or Path).
    2.  Enter Event Loop.
    3.  On `FORK` command: `os.fork()` then `importlib.import_module(user_app)`.

### Directive 2: The "Airlock" (`v_shield.rs`)
Implement the `Airlock` trait in `src/lifecycle/v_shield.rs`.
*   **Must Implement**: `enter_app_tier(cmd, user_venv_path)`.
*   **Security Rule**: Use **Allow-List** logic (Clear & Rebuild). Do NOT use Block-List (removing specific vars).

### Directive 3: Refactor Launcher (`zygote/mod.rs`)
Rewrite `ZygoteLauncher::start`:
*   **DELETE**: Logic that adds Velo libs to PYTHONPATH.
*   **ADD**: Logic that detects user python.
*   **ADD**: Logic that reads `bootstrap.py` source and injects it.
    *   **Security Rule (SEC-002)**: Use `python -c "<code>"` or pass via `stdin`. **DO NOT** write to `/tmp` to avoid TOCTOU attacks.

### Directive 4: De-Bloat
*   **DELETE/ARCHIVE**: The old `velo_zygote` heavy library.
*   **RETAIN**: Only the logic strictly needed for the Shim.

---

**Architect's Note**: do not try to "fix" the old Zygote. Replace it. The new Zygote is a User Process that we happen to control via a minimal tether (the Shim).

---

## 5. Deployment Strategy (Extended Discussion)

The Supervisor Model fits both Single-Machine and Serverless patterns, acting as a **Smart Adapter**.

### 5.1 Single Machine (VPS / Dev / Bare Metal)
**Mode**: **High-Density Supervisor**
*   **Mechanism**: Velo runs as a persistent daemon.
*   **Benefit**: Multi-tenant or Multi-worker management.
*   **Physics**: Uses **COW (Copy-On-Write)** to share memory between workers.
*   **Result**: 100 workers consume only incrementally more RAM than 1 worker. Ideal for high-concurrency monoliths.

### 5.2 Serverless (Cloud Run / Lambda / Knative)
**Mode**: **Super-Dense Serverless**
*   **The Misconception**: "Serverless = 1 Request/Process".
*   **The Velo Reality**: Serverless billing is based on **Memory-Seconds**.
*   **Mechanism**:
    *   Velo boots ONE Zygote (Pre-warmed).
    *   On concurrent requests (Cloud Run allows 80+), Velo **Forks (COW)** workers instantly.
    *   **Benefit 1 (Cost)**: 50 concurrent requests share 90% of memory. You can handle 10x traffic on the *same* memory tier.
    *   **Benefit 2 (Latency)**: Forking a pre-warmed Zygote is milliseconds. Initializing a fresh container is seconds. Velo converts "Cold Starts" into "Warm Forks".
*   **Conclusion**: Velo transforms Serverless from "Stateless Functions" into "Elastic Micro-Monoliths". Architecture serves the purpose of **Cost & Latency Reduction**.
