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

---

## 6. Advanced Optimization: Tiered Zygote Strategy (The Grand Zygote)

To support **Heterogeneous Workloads** (App A vs App B) while maximizing shared memory, V3 introduces a **Three-Tier Process Tree**. This solves the "dependency conflict" problem while retaining "base runtime sharing".

### Tier 0: The Grand Zygote (The Root)
*   **State**: "Naked" Python.
*   **Loaded**: Python VM + Standard Library (`os`, `sys`, `json`, `socket`, `asyncio`) + Velo Bootstrap Shim.
*   **Memory**: Shared across **ALL** Apps on the node (Cross-Tenant Sharing).
*   **Role**: The universal immutable template.

### Tier 1: The Project Zygote (The Branch)
*   **Creation**: Forked from Grand Zygote.
*   **Mutation**: Inject `PYTHONPATH`, run `site.addsitedir(User_Venv)`.
*   **Loaded**: User-specific dependencies (e.g., `django` vs `fastapi`).
*   **Memory**: Shares Tier 0 pages. Private pages hold App-specific deps.
*   **Role**: The per-project, pre-warmed template.

### Tier 2: The Worker (The Leaf)
*   **Creation**: Forked from Project Zygote.
*   **Action**: Handle Requests (ASGI/WSGI).
*   **Memory**: Shares Tier 0 + Tier 1 pages.

**Architectural Value**:
Even in fully heterogeneous environments (100 different apps), the heavy CPython runtime and stdlib (~15-20MB) are loaded **once** in the Grand Zygote. This saves GBs of RAM in high-density multi-tenant nodes and reduces the cold-start time (Tier 1 creation) to sub-millisecond range.

### 6.1 The Shift in Venv Management
You correctly identified a fundamental operational shift:
*   **Single-Machine Mode**: Velo acts as **Builder & Runner**. If `.venv` is missing, Velo calls `uv` to build it.
*   **Tiered/Serverless Mode**: The `.venv` becomes an **Immutable Artifact**.
    *   **No Building**: The Grand Zygote MUST NOT run `uv sync`. It assumes the `.venv` is already present (baked into the container image or mounted Volume).
    *   **Path Injection**: The Supervisor tells Tier 1: "Mutate yourself into *this* specific path: `/opt/app-a/.venv`".
    *   **Implication**: In this mode, `velo` is purely a **Runtime Supervisor**, completely decoupling from the "Build Phase".

### 6.2 The Dynamic Chain Synthesis Strategy (Memory Layering)
To achieve "Composable Memory Blocks" (Layering) while respecting Python's single-inheritance physics, V3 implements **Dynamic Chain Synthesis**.

**The Concept: Zygote as a Linear Polymer**
*   **Atom**: A specific library version (e.g., `Atom_N1 = numpy@1.24`).
*   **Molecule (Zygote)**: A linear chain of atoms (e.g., `Zygote_A = [Base, Atom_N1, Atom_P2]`).
*   **Combustion**: Forking a molecule to append new atoms.

**The Synthesis Algorithm (Greedy Prefix Matching)**:
When App X requests `[numpy@1.24, pandas@2.0, my_lib]`:
1.  **Scan**: Velo scans all active Zygotes in the "Memory Forest".
2.  **Match**: Find the Zygote with the **Longest Matching Prefix**.
    *   *Candidate A*: `[numpy@1.24]` -> (Match Length 1)
    *   *Candidate B*: `[numpy@1.24, pandas@2.0]` -> (Match Length 2) **<-- Winner**
3.  **Synthesis (Fork)**:
    *   Fork *Candidate B*.
    *   **Delta Load**: Import `my_lib`.
    *   **Result**: App X runs with `[numpy@1.24, pandas@2.0] + [my_lib]`.
4.  **Cost**: Shared Memory = Base + Numpy + Pandas. Private Memory = my_lib.

**Emergent Optimization (Crystallization)**:
If Velo observes that the transition `Candidate B -> Delta Load` happens frequently (Hot Path), it **Crystallizes** the result into a new Base Zygote (`Candidate C`).
*   **Result**: Future Apps fork directly from *Candidate C*.
*   **Vision**: The "Infrastructure Base" is not static; it **evolves** based on usage patterns, automatically finding the optimal set of "Common Memory Blocks".

### 6.3 Implementation Mechanics (The Prefix Engine)
To realize this "Memory Block Assembly", Velo (Rust) runs an internal **Prefix Matching Engine**.

**Step 1: Genome Signature (Normalization)**
*   Input: `uv.lock`.
*   Action: Sort dependencies alphabetically to create a canonical signature.
*   Example: `S = [numpy==1.24, pandas==2.0, torch==2.1]`.

**Step 2: The Zygote Trie (State)**
Velo maintains an in-memory Tree of all active Zygotes:
*   `Root` (State=[])
    *   `Node A` (State=[numpy==1.24])
        *   `Node B` (State=[numpy==1.24, pandas==2.0])

**Step 3: Longest Prefix Match (The Algorithm)**
*   Action: Match `S` against the Trie.
*   Trace: Root -> Node A -> Node B (Mismatch at `torch`).
*   **Winner**: `Node B` (matches 66% of signature).

**Step 4: Fork & Load (The Synthesis)**
*   Velo sends command to Node B: `FORK(delta=[torch==2.1])`.
*   Node B forks -> New Process (Node C).
*   Node C imports `torch`.
*   **Result**: Node C is now `[numpy, pandas, torch]`. It is added to the Trie for future reuse.
