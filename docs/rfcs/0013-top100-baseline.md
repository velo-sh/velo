# RFC-0013: Top 100 Python Project Baseline (v2)

## 1. Summary
Establish a credible, community-recognized performance baseline for Velo by benchmarking the top 100 Python projects. unlike v1 (which only tested `import`), v2 implements **Official Hello World** scenarios specific to each project type (Library, Web Framework, CLI, ML).

## 2. Motivation
To prove Velo's value to the Python community, we need a benchmark that answers: "How much faster is Velo for **real** usage?"
A simple `import package` test is insufficient because:
- It ignores initialization costs (e.g., `FastAPI()` app creation).
- It doesn't reflect how users actually invoke tools (e.g., CLIs use entry points).
- It lacks granularity across different project types.

## 3. Methodology

### 3.1 Project Selection policy
- **Source**: [hugovk/top-pypi-packages](https://github.com/hugovk/top-pypi-packages) (30-day downloads).
- **Strategy**: "Additive Hall of Fame". Once a package is standardized and added to the benchmark suite, it remains (even if it drops out of the absolute top 100), ensuring long-term regression tracking. 
- **Version Locking**: Every benchmark run must record exact package versions to ensure reproducibility.

### 3.2 "Hello World" Definition
"Hello World" is defined as the **Official Recommended Minimal Entry Point**.

**Startup Time Definition**:
From OS-level process start (`exec`) to successful completion of the benchmark entry point (script exit or explicit stdout marker).
- **Includes**: Python runtime init, module import, application object construction.
- **Excludes**: Server listen, request handling, long-running event loops, background tasks.

### 3.3 Categorization & Standards

#### Type A: Libraries (requests, numpy, pydantic)
- **Goal**: Measure import cost + basic initialization.
- **Code**:
  ```python
  import requests
  print(requests.__version__)
  ```
- **Verification**: Regex match version string.

#### Type B: Web Frameworks (FastAPI, Django, Flask)
- **Goal**: Measure framework initialization up to **successful application object instantiation**.
- **Restriction**: DO NOT start a blocking server (no `app.run()`).
- **Code**:
  ```python
  from fastapi import FastAPI
  app = FastAPI()
  print("app created")
  ```

#### Type C: CLI Tools (black, poetry, pip)
- **Goal**: Measure runtime startup optimization (highly sensitive).
- **Execution**: Use **canonical CLI entry point** (e.g., `black --version`).
- **Restriction**: NO `python -m package` wrappers.

#### Type D: ML / Data (torch, tensorflow)
- **Goal**: Python runtime + native extension init (Minimal object construction).
- **Code**:
  ```python
  import torch
  # Force initialization without triggering heavy compute/backend
  t = torch.empty(1)
  print(f"torch initialized: {t}")
  ```

### 3.4 Directory Structure & metadata
Structured, configuration-driven approach.

```text
benchmarks/top100/
├── _runner/                # Shared benchmark runner (Python)
├── library/
│   ├── requests/
│   │   ├── hello.py        # Official example
│   │   ├── benchmark.toml  # Configuration
│   │   └── meta.json       # Version history
│   ├── numpy/
│       └── ...
```

**benchmark.toml Schema**:
```toml
[meta]
category = "library" # library, web, cli, ml
description = "Requests: HTTP for Humans"

[test]
entry_point = "hello.py" # or "run.sh"
expected_output = ".*\\d+\\.\\d+\\.\\d+.*" # Regex for validation
timeout = 30
```

### 3.5 Measurement & Metrics (Multi-Level Matrix)
The runner will now measure and report **4 distinct levels** of optimization to showcase the Velo value add:

| Level | Name | Config | Mechanism | Target vs CPython |
|---|---|---|---|---|
| **L1** | **CPython** | N/A | Standard Interpreter | Baseline (1.0x) |
| **L2** | **Velo Zero** | `--zygote` | Hot Process, Cold Import | ~1.2x - 3.0x |
| **L3** | **Bundle** | `--zygote --fast` | Hot Process, Single-File IO | IO Dependent |
| **L4** | **Instant** | `--zygote --fast` + `preload` | **Mem-resident Modules** | **10x - 50x+** |

**Metric Collection**:
- Runner must automatically:
    1.  **L3 Setup**: Run `bundle_builder.py` to generate `.veloc`.
    2.  **L4 Setup**: Inject `preload` config into temporary `pyproject.toml`.
- **Validation**: Pass/Fail checked at highest level (L4). Lower levels just report times.

## 4. Implementation Plan

### Phase 1: Prototype (Top 5) [COMPLETED]
- Verified Basic Zygote (L2) works.
- Identified L3/L4 gaps (Bundle Hash, Preload Config).

### Phase 1.5: Multi-Level Runner Upgrade [ACTIVE]
- **Runner**: Refactor `main.py` to support the 4-level loop.
- **Tooling**: Integreate `bundle_builder.py` directly into runner.
- **Config**: Add `preload_modules` list to `benchmark.toml`.

### Phase 2: Expansion (Top 20)
- Apply new runner to Top 20 packages.

## 5. Success Criteria
- **Quality**: Each benchmark represents idiomatic usage.
- **Stability**: Standard deviation < 5%.
- **Automation**: Fully runnable in CI.
