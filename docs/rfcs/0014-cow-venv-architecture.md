# RFC-0014: Top 100 Benchmarks with Zygote Integration

**Status**: Draft (Revised)
**Created**: 2026-01-07
**Author**: Antigravity (Agent)

## 1. Summary

This RFC proposes integrating Velo's **existing Zygote infrastructure** (`ZygoteLauncher`) into the Top 100 Benchmark Runner. Instead of re-implementing a custom Copy-on-Write (CoW) system, we will leverage the mature, production-tested Zygote capabilities to accelerate benchmark execution.

The implementation follows a **Two-Phase Strategy**:
1.  **Phase 1 (Execution Speedup)**: Integrate `ZygoteLauncher` to replace `subprocess.run()`. Accelerates test execution via memory CoW but retains per-test venv creation.
2.  **Phase 2 (Setup Tax Elimination)**: Introduce **Shared Venv** strategy to eliminate the repeated `uv venv` and `pip install` overhead.

## 2. Motivation

The primary bottleneck in Top 100 regression testing is the **Setup Tax**:

| Operation | Current Time | Frequency | Total Time (100 pkgs) |
|-----------|--------------|-----------|-----------------------|
| `uv venv` | ~0.5s | 100 | ~50s |
| `uv pip install` | ~5-30s | 100 | ~15-20 min |
| **Total Setup** | | | **~25 min** |

**Goal**: Reduce this overhead significantly while ensuring test isolation.

## 3. Architecture

### 3.1 Core Principle: Reuse, Don't Rebuild

Velo already possesses robust CoW capabilities:
*   **Rust**: `ZygoteLauncher` handles process lifecycle and IPC.
*   **Python**: `ForkHandler` manages `fork()`, FD sanitization, and RNG reseeding.
*   **Security**: Existing `EnvironmentShield` and `SandboxShield`.

We will apply these capabilities to the Benchmark Runner rather than building a new `cow_runner.py`.

### 3.2 Two-Phase Strategy

#### Phase 1: Zygote Integration (Immediate Value)
Focus: **Faster Test Execution**
*   Benchmark Runner uses `ZygoteLauncher.spawn_worker()` instead of `subprocess.run()`.
*   Zygote preloads common modules (e.g., `json`, `sys`) to speed up startup.
*   **Trade-off**: Still creates individual venvs for each test to ensure compatibility, so Setup Tax remains.
*   **Gain**: Execution time drops from seconds to milliseconds; validates Zygote stability for Top 100.

#### Phase 2: Shared Venv (Strategic Goal)
Focus: **Eliminate Setup Tax**
*   Create a `.shared_venv/` containing **all** Top 100 dependencies.
*   Zygote pre-warms this massive environment.
*   Tests reuse this environment, skipping `uv pip install` entirely.
*   **Challenge**: Dependency version conflicts (Dependency Hell).
*   **Solution**: **Compatibility Groups** (General, ML, Web) to isolate conflicting packages.

## 4. Implementation Design

### 4.1 Benchmark Runner Updates (`main.py`)

Add a `--use-zygote` flag to switch execution modes:

```python
class BenchmarkRunner:
    def __init__(self, use_zygote: bool = False, ...):
        self.use_zygote = use_zygote
        if use_zygote:
            self._start_zygote()

    def _start_zygote(self):
        # Start Velo Zygote with configured preload modules
        self.launcher = ZygoteLauncher.new(...)
        self.launcher.start(preload=self.preload_config)

    def run_benchmark(self, ...):
        if self.use_zygote:
            # Spawn worker via IPC
            handle = self.launcher.spawn_worker(script_path, ...)
            handle.wait()
        else:
            # Legacy subprocess
            subprocess.run(...)
```

### 4.2 Security & Isolation

We inherit Velo's existing security features:
*   **Thread Safety**: `OMP_NUM_THREADS=1` is already enforceable via Zygote config.
*   **FD Sanitization**: `post_fork_reinit()` automatically closes non-whitelisted FDs.
*   **CUDA Guard**: Will verify if `check_cuda_initialized()` covers the benchmark use cases.

## 5. Verification Plan

### 5.1 Phase 1 Verification
*   **Functional**: 100/100 packages pass with `--use-zygote`.
*   **Isolation**:
    *   **Entropy Test**: Verify `uuid.uuid4()` uniqueness across workers.
    *   **Env Isolation**: Verify `os.environ` changes don't leak.
*   **Performance**: Execution time < 50% of subprocess mode.

### 5.2 Phase 2 Verification
*   **Setup Elimination**: `venv` creation time = 0s.
*   **Conflict Resolution**: Compatibility Groups successfully segregate conflicting deps (e.g., `numpy` versions).

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Dependency Hell (Phase 2)** | Tests fail due to version mismatch | Use `uv pip compile` to analyze conflicts; implement Compatibility Groups. |
| **CUDA Initialization** | Fork crash on ML packages | Use `CUDA_VISIBLE_DEVICES=""` during Zygote warmup (already supported). |
| **Zygote Instability** | Benchmark runner crash | Keep `subprocess` mode as a stable fallback. |
