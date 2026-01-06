This document combines the conceptual metaphor and technical implementation details of Velo's Zygote process pre-warming system.

> **Branding Note**: While "Zygote" is the internal technical codename, all public-facing documentation and marketing should use the brand name **Velo** (e.g., "Velo is 14x faster").

---

## 1. Concept: The 'Fertilized Egg' Metaphor

### 1.1 Biological Origin
In biology, a **Zygote** is the eukaryotic cell formed by a fertilization event between two gametes. It is the beginning of a life form—a single cell containing all the genetic information needed to develop into a complex organism. It is a state that is "ready to divide."

### 1.2 Computer Science Metaphor
Velo's Zygote mode is inspired by the Android OS and Chrome's process pre-warming.

| Term | Concept | Velo Implementation |
|------|---------|---------------------|
| **Zygote Parent** | The "Fertilized Egg" | A resident Python process with heavy libraries (FastAPI, NumPy) already loaded. |
| **fork()** | Cell Division | A rapid system call to clone the parent process into a worker. |
| **COW (Copy-on-Write)** | Shared Resource | OS-level memory sharing between parent and child. |

### 1.3 Speed Benchmarks
The Zygote breaks the **Module Execution Barrier**. 

- **Normal Start**: `spawn → load Python → find modules → parse bytecode → EXECUTE module top-level → run script`.
- **Zygote Start**: `fork parent (modules already executed) → run script`.

**Micro Speedup**: Up to **49x** (0.5ms vs 25ms saved on simple logic).
- **Industrial Target (with Preload)**: **43ms** (93% speedup vs CPython 606ms), achieving a **14.0x** multiplier.

---

## 2. Architecture Overview

```mermaid
graph TD
    A[Velo CLI] -- Unix Socket --> B[Zygote Daemon (Python)]
    B -- fork() --> C[Worker Process (Python)]
    C -- exec() --> D[User Script]
```

## 3. Hybrid Daemon Model

Velo supports both constant daemon and on-demand modes:
- **On-Demand**: First `run --zygote` starts and warms up the process.
- **Daemon**: Manual start via `velo zygote start`.
- **Idle Timeout**: Shuts down after 5 minutes of inactivity in on-demand mode.
- **CLI Default (v0.6.2+)**: Zygote pre-warming is now **ENABLED BY DEFAULT** for `velo serve`. Use the `--no-zygote` flag to disable this feature for specific debugging sessions.

- **macOS Fork Safety (2026-01-06)**: macOS's Objective-C runtime implements strict safety checks for `fork()` from multi-threaded processes (e.g., when the Zygote has an active `asyncio` event loop).
  - **The Defect**: Workers forked in this state crash immediately without executing any Python code.
  - **The Workaround**: Use the environment variable `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`. Velo's `ZygoteLauncher` (Rust) automatically applies this for macOS targets.
  - **Risk Assessment**: While this suppresses the crash, it requires ensuring that the forked worker reset state deterministicly via `post_fork_reinit()`.
- **Windows**: **Not supported** (lacks `fork()`). Falls back to standard mode.

### 5.1 Asyncio Migration & Command Dispatcher
The Zygote implementation has been modernized to use `asyncio`, enabling non-blocking handling of multiple concurrent IPC requests and providing a more robust base for the control plane.

- **`ZygoteServer`**: Uses `asyncio.start_unix_server` for its main loop.
- **Command Dispatcher**: Formalizes the IPC contract by mapping request types to handler methods. Supported commands: `Fork`, `Status`, `Ping`, `Shutdown`, `WorkerStatus`.
- **Ready ACK**: On connection, the Zygote sends `{"type": "Ready"}` to signal it's warmed up and ready to accept commands.

### 5.2 Standardized Worker Launching
To improve auditability and security, Velo has replaced dynamic script generation with a standardized **`worker_launcher.py`** module.
- **CLI Arguments**: The Rust supervisor passes worker configuration (socket path, app name, etc.) via CLI arguments to the launcher.
- **Integration**: The launcher handles `uvicorn` setup and `post_fork_reinit()` execution directly, eliminating temporary file risks.

### 5.3 FD Hive & Security (Phase 3.A)
Velo implements **Whitelist-based FD Hygiene** to ensure that sensitive file descriptors (e.g., database handles, supervisor logs) do not leak into child processes.

- **Rust Cleanup (`ZygoteLauncher`)**: On startup, the Rust supervisor executes `set_cloexec_on_all_fds` in `ZygoteLauncher::start()`, which scans `/proc/self/fd` and marks all descriptors > 2 as `CLOEXEC`.
- **Worker Cleanup (`post_fork_reinit`)**: Immediately after forking, the worker identifies all open FDs and closes everything except:
  - `stdin` (0), `stdout` (1), `stderr` (2)
  - The Zygote IPC socket.
- **FD Discovery**: Accomplished by scanning `/proc/self/fd` on Linux or using `os.closerange` for broad sweeps on unsupported platforms.
- **The 'Ready Signal Suppression' Trap**: Overly aggressive FD closure (e.g., `os.closerange(3, max_fd)`) can inadvertently close file descriptors used for log streaming or "ready" signals (stdout/stderr) if uvicorn or the test fixture depends on inherited handles. Whitelist-based closure is MANDATORY to prevent `TimeoutError` during server startup.

### 5.4 CUDA Check & Library Safety
To prevent deadlocks and context corruption in HPC stacks (PyTorch/NumPy), Velo implements a multi-tier safety check:

- **Check Placement**: Velo performs the `check_cuda_initialized()` call inside `ZygoteServer.start` immediately after libraries are preloaded. This catches contexts created during library initialization or via `LD_PRELOAD`.
- **Heuristic Defense**: If a context is detected, the Zygote daemon refuses to fork and logs a FATAL error, forcing the user to resolve the import order issue.
#### 5.4.1 Pillar 1: EnvShield Whitelist
To maximize security while maintaining toolchain stability (VIRTUAL_ENV/uv), Velo enforces a strict environment passthrough whitelist:
1. **Essential OS**: `PATH`, `HOME`, `USER`, `TMPDIR`, `XDG_RUNTIME_DIR`, `SHELL`.
2. **Platform Context (macOS)**: `XPC_FLAGS`, `XPC_SERVICE_NAME`, `TERM_PROGRAM`, `__CF_USER_TEXT_ENCODING`, `MallocNanoZone`.
3. **Python Toolchain**: `PYTHONPATH`, `VIRTUAL_ENV`, `CONDA_PREFIX`.
4. **Localization**: `LANG`, `LC_ALL`, `LC_CTYPE`.
5. **Velo Guards**: `PYTHONDONTWRITEBYTECODE="1"`, `PYTHONUTF8="1"`.
6. **HPC Isolation**: `OMP_NUM_THREADS="1"` (and variants for MKL, OpenBLAS, VecLib).

### 5.5 Abstract Sockets (Linux Optimization)
For industrial deployments on Linux, Velo supports **Abstract Namespace Sockets** (`\0velo-...`) to improve reliability.
- **Benefit**: They eliminate the risk of "Stale Socket" files and permission conflicts in `/tmp`.
- **Implementation**: `ZygoteLauncher` uses `ipc::is_socket_alive` to detect Zygote presence, which correctly handles abstract sockets by skipping filesystem `exists()` checks for paths starting with a null byte.
- **CLI Bridge**: When spawning the Python Zygote, Rust converts the leading null byte to an `@` sentinel (e.g., `@velo-zygote...`) to ensure it can be passed via command-line arguments.
- **Python Re-conversion**: The Python `ZygoteServer` converts the `@` prefix back to a null byte (`\0`) in its constructor.
- **Filesystem Bypass**: For abstract sockets, Velo automatically skips `path.exists()` and `path.unlink()` operations in both the Rust supervisor and the Python daemon, as abstract sockets are managed by the kernel and do not exist as files.

### 5.6 Grandchild Synchronization
CLI polls for the existence of an **exit code sentinel** file created by Zygote *after* worker exit. This overcomes the `ECHILD` restriction where a parent cannot `waitpid` on a grandchild.

**WorkerHandle API Extensions (RFC-0008)**:
The `WorkerHandle` provides access to the low-level process details:
- `pid()`: Returns the worker's PID.
- `stdout_path()` / `stderr_path()`: Returns optional paths to the temporary I/O capture files.
- `wait()`: Blocking call that returns the exit code once available.

---

## 6. Troubleshooting & Development Traps

### 6.1 The Stale Socket Trap
If the daemon crashes, the socket file remains. CLI implements a "Retry-on-Stale-Socket" loop.

### 6.2 The Relative Path Trap
Zygote's CWD might differ from the CLI. All paths must be canonicalized to absolute paths before transmission.

### 6.3 Configuration: Single Source of Truth
Historically, Velo used `velo.toml`. As of Phase 4.1, this is **Prohibited**.
- **Standard**: All preloads and settings must reside in `pyproject.toml` under `[tool.velo]`.
- **Reason**: Alignment with PEP 518/621 and reduction of configuration fragmentation.
- **The Heuristic Dependency Trap (Forensic 51)**: Zygote activation is coupled with framework detection (FastAPI/Django). In isolated testing environments (like `tmp_path`), if the project manifest (`pyproject.toml`) is missing, framework detection defaults to `Unknown`. The Rust supervisor will silently disable Zygote pre-warming for performance reasons (assuming as trivial app), even if `--zygote` is explicitly requested.

### 6.4 Security: The Path Traversal Trap
Velo uses a **Blocklist** of system paths (e.g., `/etc`, `/usr`) to prevent traversal while allowing execution in temporary CI environments.

### 6.5 The Profiling/Async Ambiguity
`--async` and `--profile` are **Mutually Exclusive**. 
- **Rationale**: Profiling requires the worker to survive and the CLI to wait for all trace data to be written to disk. Detaching the process via async mode would lead to truncated or missing profile reports.
- **Implementation**: The CLI throws a strict error (code 1) if both flags are provided simultaneously.

### 6.6 Framework Execution Bottlenecks (2026-01-03)
Production tracing pinpointed why the Fast Loader (I/O optimization) is insufficient for complex frameworks:

| Operation | Time | Constraint |
|-----------|------|------------|
| `python -c "pass"` | 96ms | Interpreter overhead (Saved by Zygote) |
| `import pydantic` | 220ms | Metaclass execution |
| `import fastapi` | **414ms (in fork)** | Remaining cost if NOT preloaded |

**Key Breakthrough (2026-01-03)**:
Zygote's "Warm" state previously referred only to the **Daemon (Interpreter)**. However, the forked worker still incurred the **Framework Execution Gap** (e.g., 414ms for FastAPI). To bridge this, the framework itself must be part of the Zygote's pre-loaded memory space.

**Conclusion**: Since initialization logic dominates modern Python frameworks, the **Zygote Mode + Preload** is the ONLY architecture that achieves sub-100ms cold starts by converting execution time into static memory inheritance. Manual verification (2026-01-03) confirmed that **automated framework preloading** drops FastAPI startup to **43ms**.

### 6.7 The App Import Gap (2026-01-06)
Workers forked from Zygote execute application code via `exec()`. A common failure mode is `Could not import module "main"`.
- **Root Cause**: Zygote's current working directory (CWD) or `sys.path` does not include the application code. This occurs when `velo serve` is run from the project root but the app resides in a subdirectory, or in isolated test environments.
- **Remediation**: Velo's `ZygoteLauncher` ensures the parent process CWD is preserved or absolute paths are used for the ASGI app import string.

### 6.8 The macOS 'Fork Safety' Ghost (2026-01-06)
A silent failure where forked workers crash before executing any Python user code or writing debug logs.
- **The Defect**: macOS Objective-C runtime detects a `fork()` from a multi-threaded parent (the Zygote's `asyncio` loop) and aborts the child process.
- **The Symptom**: Workers reported as "Died" with exit code 1 or 0.
- **Deep Discovery**: Forensics (Commit `9cf2e8a` and `4a1c71c`) revealed that once the common `fork-after-thread` crash is bypassed (via `OBJC_DISABLE_INITIALIZE_FORK_SAFETY`), a secondary "Ghost" can appear: The child process successfully executes Python code up to the point of networking initialization (e.g., `uvicorn.run()`), but then exits with `SystemExit: 1` without producing standard error logs.
- **Manual Reproduction**: standalone execution of `worker_launcher.py` with captured Zygote arguments (`python3 worker_launcher.py --app ...`) reliably yields **Exit Code 1**, proving the defect is localized to the worker launcher's startup logic or environment compatibility rather than the fork call itself.
- **The Final Breakthrough (2026-01-06)**: The "Ghost" was unmasked as a **Module Shadowing Conflict**. Forensic traces proved that because `worker_launcher.py` is in `velo_zygote/`, `import main` was loading the Zygote supervisor itself (`velo_zygote/main.py`) instead of the user's `main.py`. This is because Python prepends the script's directory to `sys.path[0]`.
- **Root Cause**: Internal infrastructure code (launcher) shadowing application-level modules of the same name.
- **The Resolution**: Institutionalized **Surgical Path Sanitization**. The worker launcher now manually removes its own directory from `sys.path` before calling `uvicorn.run()`. This ensures user application modules (normally in the CWD) are correctly prioritized.

### 6.9 File-Append Trace Technique (2026-01-06)
When debugging forked processes on platforms where `stderr` might be closed or redirected by the framework (macOS/Uvicorn), internal print statements often vanish.
- **Strategy**: Implement an atomic `debug_log` function inside the `_child_process` entry point that opens a file in **append mode** and writes immediately.
- **Implementation**:
  ```python
  def debug_log(msg):
      with open("/tmp/worker_debug_trace.log", "a") as f:
          f.write(f"[{os.getpid()}] {msg}\n")
  ```
- **Utility**: This bypasses all `sys.stderr` redirection and confirms exactly which step of the `post_fork_reinit` or `exec()` sequence the worker reached before crashing.

### 6.10 The Event Loop Death Spiral (2026-01-06)
A critical race condition can occur in the Zygote supervisor's `asyncio` loop during rapid worker crash/recovery cycles (`GOLD-006`).
- **The Defect**: `RuntimeError: Event loop stopped before Future completed.`
- **The Symptom**: The Zygote process crashes or becomes unresponsive to IPC requests, leading to "Connection refused" errors in the Rust supervisor.
- **Root Cause**: If a worker crash triggers a re-fork request while the event loop is transitioning states or shutting down, pending futures may be orphaned.
- **Mitigation**: Ensure loop-safe signal handling using `loop.call_soon_threadsafe` and robust error handling in the `CommandRouter`.

### 6.11 The App Loading Sequence (2026-01-06)
To maximize the "Pre-warm" benefit, it's crucial to understand where code execution happens:
1. **Zygote Parent**: Preloads framework modules (FastAPI, uvicorn) specified in `pyproject.toml`.
2. **Worker Launcher**: Handled by the forked child. It loads the **user application** (e.g., `main:app`).
- **Strategic Insight**: If the user app has high-cost top-level execution logic, it should be moved to the Zygote preload list to achieve the 43ms target.

### 6.12 Call-Wrap Diagnostic Pattern (2026-01-06)
To capture crashes that occur during the function call handoff between the Zygote's command handler and the worker entry point (e.g., argument serialization errors or immediate startup exceptions), the call site MUST be wrapped in a global exception handler.
- **Implementation**:
  ```python
  try:
      ForkHandler._child_process(...)
  except BaseException as e:
      # Log failure to a persistent debug file
      with open("/tmp/worker_fork_debug.log", "a") as f:
          f.write(f"[FORK DEBUG] Call CRASHED: {e}\n")
          f.write(traceback.format_exc())
      os._exit(1)
  ```
- **Rationale**: This prevents the "Silent Ghost" where a child process disappears during the transition into user code, providing immediate traceability for environment or configuration mismatches.

### 6.13 Surgical Path Sanitization Pattern (2026-01-06)
Infrastructure scripts that are co-located with the framework but need to execute user code MUST sanitize `sys.path` to prevent shadowing internal modules.
- **The Problem**: Running `python bin/launcher.py` adds `bin/` to `sys.path[0]`. If `bin/` contains a `main.py`, it will shadow a `main.py` in the user's current directory.
- **The Pattern**:
  ```python
  # Identify the location of the infrastructure script
  script_dir = os.path.dirname(os.path.abspath(__file__))
  # Surgical removal to allow user modules to prevail
  if script_dir in sys.path:
      sys.path.remove(script_dir)
  
  # Ensure CWD is at the front
  if os.getcwd() not in sys.path:
      sys.path.insert(0, os.getcwd())
  ```
- **Benefit**: Achieves strict isolation between the runtime engine and the application it is serving, specifically preventing "Attribute not found" errors during ASGI app loading.

### 6.14 Python Interpretation Drift (2026-01-06)
In isolated development environments (e.g., using `uv run` or `conda`), multiple Python interpreters may exist simultaneously.
- **The Defect**: If the Zygote supervisor's discovery logic selects a different Python binary than the one used to install the application dependencies (e.g., system python vs .venv python), workers will crash with `ModuleNotFoundError` for packages like `uvicorn` or `fastapi`.
- **The Standard**: The Zygote launcher (Rust) MUST prioritize the active virtual environment (`.venv` in project root or `$VIRTUAL_ENV`) and log the absolute path of the selected interpreter for auditability.
- **Verification**: `DEBUG: Zygote starting with Python: "/path/to/venv/bin/python"` must be verified in logs to confirm alignment.

### 6.10 Anatomy of 43ms: Where is the Gap? (2026-01-03)

Profiling the 43ms "Instant Tier" performance revealed a technical ceiling in the current synchronous architecture:

1. **Host Boot (10ms)**: Rust CLI binary loading and argument resolution.
2. **IPC Round-trip (1ms)**: Communication with the Zygote daemon.
3. **Division (0.7ms)**: The OS `fork()` call itself is negligibly fast.
4. **The Ghost Gap (~31ms)**: The CLI synchronously waits for the worker process to signal completion and flush stdout.

**Optimization Frontier (RFC-0008)**:
The Phase 5.1 initiative (`phase-5.1/zygote-optimization`) formally addresses this tax through:
- **Asynchronous Spawn**: Allowing the CLI to disconnect as soon as the worker starts via `--async`.
- **Background Logging**: Redirecting output to files to preserve non-blocking performance while maintaining visibility.
- **Worker Pools**: Pre-forking workers to move the 0.7ms fork cost into the background.

## 7. Auto-Configuration Workflow

Velo provides a data-driven toolchain to identify and configure preload modules without manual guesswork.

### 7.1 The Three-Step Workflow
1.  **Profiling**: Run the application once with profiling enabled to capture import timings.
    ```bash
    velo run --profile main.py
    ```
2.  **Analysis**: Use the auto-config utility to parse the profile and identify modules exceeding the 50ms execution threshold.
    ```bash
    velo zygote auto-config
    ```
3.  **Persistence**: Copy the generated TOML block into your `pyproject.toml`.
    ```toml
    [tool.velo]
    preload = ["fastapi", "uvicorn", "pydantic"]
    ```

### 7.2 Implementation: `src/zygote/auto_config.rs`
-   **Threshold**: Defaults to **50ms** (`PRELOAD_THRESHOLD_SECS`).
-   **Limit**: Caps at **10** modules (`MAX_PRELOAD_MODULES`) to prevent memory bloating.
-   **Methodology**: Analyzes `top_imports` from the profile data and maps them to top-level package names.

### 7.3 Robust Component Discovery (Implemented 2026-01-03)
Zygote previously failed with `Could not find velo_zygote/main.py` when executed from directories other than the project root.
- **Resolution**: Implemented a **6-Tier Path Discovery** in `src/zygote/mod.rs`:
  1. **`VELO_ZYGOTE_PATH`**: Explicit environment variable override.
  2. **Compile-Time Embedding**: Uses `env!("CARGO_MANIFEST_DIR")` to bake the development source path into the binary.
  3. **Executable-Relative**: Searches parent directories of the `velo` binary (standard for installed/portable builds).
  4. **User Install**: `~/.local/share/velo/`.
  5. **System Install**: `/usr/local/share/velo/`.
  6. **CWD Fallback**: Current working directory.
- **Result**: Zygote now works instantly in development contexts regardless of the current working directory, eliminating the need for manual symlinks.

### 7.4 The Configuration Bridge Resolved (DEV-FIX-001)
Successfully implemented the bridge between `pyproject.toml` and the Zygote daemon.
- **Resolution**: `velo run --zygote` now automatically parses `[tool.velo].preload` and passes it to the daemon.
- **Performance Impact**: Reduced FastAPI cold starts from **470ms** down to **43ms** (a 93% speedup versus baseline).

### 7.5 Pre-warm Setup Automation (v0.5.1)
The benchmarking toolchain (`benchmark_projects.py`) has been upgraded to **self-configure**:
- **Automatic Configuration**: Injects the `[tool.velo]` section into `pyproject.toml` based on `uv` dependencies.
- **Automatic Discovery**: Handles `velo_zygote` symlinks to ensure the daemon can immediately initialize components.
- **Impact**: Zero-manual-tuning requirement for sub-50ms framework benchmarks.

## 8. Zygote Pre-Warming: Formal Requirements (v0.5.1)

To fully institutionalize the performance gains, the following requirements are established for the next release cycle:

### 8.1 DEV-FIX-001: Configuration Bridge Pattern (Implemented 2026-01-03)
The CLI automatically parses `pyproject.toml` and passes the `preload` list to the Zygote daemon:
- **REQ-1**: `velo run --zygote` identifies `pyproject.toml` in the working directory.
- **REQ-2**: Parses the `[tool.velo].preload` string array.
- **REQ-3**: Bridges these modules to the daemon via the `--preload` CLI argument during auto-start.
- **Implementation Status**: ✅ **Implemented and Verified** (Commit `f0161a4`).
- **Performance Details**: Verified with `bench_fastapi`: Zygote automatically pre-warms frameworks and achieves **43ms** startup (14.0x speedup).

### 8.3 RFC-0008: Async Mode & Managed IPC (Implemented 2026-01-03)
RFC-0008 optimizes the IPC between the CLI and daemon to reach sub-20ms goals.
- **Async Mode**: Added `--async` flag to `velo run`. Zygote returns a PID immediately, and the CLI exits with code 0 while background I/O is redirected to temporary files.
- **Orphan Guard**: Implemented `WorkerSafety` guardian thread in Python to prevent zombie leakage via PID tracking and TTL.
- **Managed Wait**: In sync mode, the Zygote daemon now waits for the child process and returns the exit code directly in the response, eliminating the 30ms "Ghost Gap" caused by CLI-side file polling.
- **Implementation Status**: ✅ **Implemented and Verified** (Commit `e681691`)
- **QA Verification**: Confirmed via `slow.py` test case: Async CLI exit in **10ms** (386x speedup) with successful background stdout/stderr capture.

### 8.2 QA-REQ-001: Performance Verification Matrix
Verification of the 55% speedup claim must be automated:

| ID | Case | Target |
|:---|:---|:---|
| **PERF-PRELOAD-001** | Manual `--preload` mapping | < 300ms |
| **PERF-PRELOAD-002** | Automated `pyproject.toml` mapping | **43ms** ✅ |
| **MERGE-001** | Preload Merge Strategy Union | ✅ Verified |
| **REG-001** | Baseline (No preload) | ~450-500ms |

### 8.3 REQ-5: Preload Merge Strategy

To ensure seamless integration between manual tuning and automated discovery, Zygote implements a **Union and Deduplicate** strategy for preloading modules.

**Conflict Resolution Hierarchy**:

1. **`pyproject.toml`** (Highest Priority): Direct user intent in the project configuration.
2. **CLI `--preload`** (Medium Priority): Ad-hoc overrides for specific benchmark runs.
3. **Auto-Detect** (Lowest Priority): Suggestions from background profiling or future automated discovery.

**Logic**:
- The final preload list is the **union** of all sources.
- Modules are de-duplicated while preserving the order of discovery (Priority 1 -> 2 -> 3).
- No source "overwrites" another; they are additive to maximize memory inheritance and performance.

---
---

## 9. Fast Mode Integration (BUG-51-001)

As of Phase 4 Stability Remediation, the Zygote supports seamless integration with Velo's **Fast Loader** (bundle-accelerated imports). This ensures that even "warm" workers benefit from the O(1) import performance for frameworks not included in the static preload.

### 9.1 IPC Protocol Sync (Tunneling)

The `ZygoteCommand::Fork` protocol (Rust) was extended to tunnel the necessary metadata to the daemon:

```rust
pub enum ZygoteCommand {
    Fork {
        script_path: PathBuf,
        fast_mode: bool,          // BUG-51-001: Pass fast activation 
        bundle_path: Option<PathBuf>,
        project_root: Option<PathBuf>,
        max_bundle_size: Option<u64>,
        // ...
    }
}
```

### 9.2 Worker Side Activation

The Python-side `velo_zygote/main.py` interprets these fields and activates the loader *immediately after fork* but *before* user code execution.

```python
# Implementation: ForkHandler._activate_fast_mode
if fast_mode and bundle_path:
    from velo_loader import activate_fast_mode
    _bundle = activate_fast_mode(Path(bundle_path), Path(project_root), max_bundle_size)
```

### 9.3 Verification: The Rust Gate

To ensure P0 security (H-4 Marshal Bomb protection), the CLI performs a **"Rust Gate"** check using `load_and_verify` before even talking to the Zygote daemon. If the bundle is compromised, the fork request is never sent, and Velo falls back to standard imports.

## 10. Observability & Configurability (PR #7)

To improve operational visibility, Zygote now supports extended status reporting and configurable timeouts.

### 10.1 `velo info` Integration
The `velo info` command now displays the active Zygote state by querying the IPC socket:
- **Zygote PID**: The process ID of the resident daemon.
- **Preloaded Modules**: A list of libraries currently residing in Zygote memory.

### 10.2 Configurable Timeouts
Users can now tune Zygote responsiveness via `pyproject.toml` to handle environments with high I/O latency:
```toml
[tool.velo]
zygote_worker_timeout = 60    # Seconds to wait for worker completion
zygote_socket_timeout = 20    # Seconds to wait for socket startup
```

### 10.3 Protocol Refinement (Shutdown Ack)
Fixed a protocol mismatch where the `Shutdown` command lacked a response. The Python Zygote now returns a `{"type": "Ready"}` acknowledgment before closing the socket, ensuring the CLI cleanly disconnects without "Broken Pipe" warnings.

---
## 11. Supervisor Lifecycle & RAII (Phase 6.1)

In supervisor mode (`velo serve`), the Zygote's lifecycle is tied strictly to the server process via **Explicit RAII Resource Management**.

### 11.1 The Zygote Guard Pattern
To prevent the detached Zygote process (which uses `setsid()`) from persisting as an orphan after a server crash or Ctrl+C, Velo implements a scope-guard:

- **Logic**: `run_server` holds an `Option<ZygoteLauncher>` guard.
- **Cleanup**: When the supervisor exits or panics, the guard's `Drop` implementation automatically calls `launcher.stop()`.
- **Signal Forwarding**: SIGINT/SIGTERM signals captured by the Event Bus trigger a graceful shutdown sequence that includes stopping the Zygote.

### 11.2 The Existing Zygote 'Shadow Trap' (Resolved)
A critical implementation edge case occurs when `velo serve` is started while a Zygote is already running:
- **The Resolution**: `runner.rs` was updated to ensure that while pre-warming is skipped for existing sockets, the `_zygote_guard` MUST be populated via `_zygote_guard = Some(ZygoteLauncher::new(socket_path))`.
- **Deep Handshake**: To prevent hanging on stale or incompatible sockets, the supervisor now performs a synchronous `ZygoteCommand::Handshake` before re-using any existing Zygote connection. This ensures the RAII lifecycle is maintained and the server correctly enters Zygote-division mode instead of silently falling back to standard uvicorn mode (Audit Remediation Fix).

### 11.3 The 'Clone Army' Trap (Resolved)
A fundamental property of `os.fork()` without `exec()` creates a visibility challenge for auditors:
- **The Defect**: Workers forked from the Zygote inherit the parent's `cmdline`. They appear in the process table as duplicate Zygote processes.
- **The Resolution**: Lineage verification MUST use parent-child relationship checks. A process is identified as a **Worker** if its PPID exactly matches the Zygote Supervisor's PID.

### 11.4 The IPC Type Mismatch (Resolved)
Serialization gaps between Rust (`rmp-serde`) and Python (`umsgpack`) can cause fatal protocol errors:
- **WaitWorker Trap**: Historically, Python returned `None` (unit value) for `WaitWorker` when Rust expected a `u32`.
- **The Resolution**: `velo_zygote/main.py` was updated with a `_smart_unpack` decoder that explicitly handles `SignalWorker`, `WaitWorker`, and `WorkerStatus`. The handlers now return explicit `0` (or the actual exit code) to satisfy Rust's `u32` requirement.

### 11.5 The Supervisor Orphan Guard (Audit-611-002)
To align with the **H-11 (Process Stability)** invariant, the Zygote supervisor itself is now protected against orphanhood:
- **The Defect**: If the Rust launcher was killed with `SIGKILL`, the Python Zygote supervisor (which uses `setsid()`) could persist as a background daemon, leading to stale socket errors on retry.
- **The Guardian**: A guardian thread in `velo_zygote/main.py` monitors the parent PID (`os.getppid()`). If the parent dies, the supervisor triggers an immediate `os._exit(1)`. This thread runs with a **1s polling interval** (Audit Remediation for H-11).
- **The WorkerRegistry.kill_all**: The Zygote server now executes `self.worker_registry.kill_all()` in its final `finally` block. This ensures that even if the Zygote process is terminated gracefully, all active workers are explicitly reaped, preventing orphan leaks.

### 18.2 Unique Authority (Master Review Red Line)
Hyper's connection pool uses the URI authority (host/port) as the primary cache key. Since all workers use Unix Domain Sockets, they lack a standard authority.
- **The Risk**: Without unique authorities, the L7 Proxy might reuse a connection to Worker A for a request meant for Worker B.
- **The Solution**: Every `SocketTarget` generates a unique virtual authority: `worker-{id}@velo`. This ensures strict isolation in the Hyper connection pool.

### 18.3 Buffer Tuning (RFC-0011 D.3)
For high-throughput local IPC, Velo bypasses system defaults:
- **Default (64KB)**: Leads to excessive context switches under load.
- **Optimized (256KB)**: Recommended by RFC-0011 for industrial workloads.
- **Implementation**: `libc::setsockopt` is used to force `SO_SNDBUF` and `SO_RCVBUF` on both sides of the UDS connection.

### 18.4 Connection Pool (RFC-0011 D.2)
- **Idle Timeout**: Set to 30s (UDS connections are low-cost to maintain).
- **Max Idle**: 1 per worker (optimal for point-to-point worker dispatch).

--
## 12. Python Zygote Reform (Phase 4 - 2026-01-05)

The Python Zygote implementation was refactored into a **Hexagonal Architecture** to decouple core server logic from transport, command handling, and worker state management.

### 12.1 Core Architectural Components
- **`ZygoteServer`**: The central orchestrator managing initialization, the resource guard, and the main request loop.
- **`ZygoteTransport`**: Encapsulates `asyncio` stream I/O and protocol framing. Handles length-prefixed MessagePack sending/receiving.
- **`CommandRouter`**: Implements a decorator-based command dispatching mechanism using the Open/Closed Principle.
- **`WorkerRegistry`**: Atomically manages worker PIDs, metadata, and asynchronous process reaping (`WorkerRegistry.reap_stale`). Includes the `Guardian` thread to prevent orphan processes.
- **`ReinitHooks`**: A modular registry for managing post-fork state re-initialization (Security, Computing, Telemetry hooks).

### 12.2 Benefits
- **Modularity**: Individual components (like transport or registry) can be tested and modified independently.
- **Extensibility**: New commands can be added via simple decorators (`@router.handler("NewCmd")`).
- **Resilience**: Dedicated registries for state reset ensure that every forked worker starts from a clean, deterministic state.

## 13. Security Invariants (Implemented)
- **Path Whitelisting**: The system shifted from a simple blocklist to verifying workspace boundaries.
- **RAII Integration**: The Rust supervisor matches this OOP structure on the guest side, ensuring a symmetric lifecycle.

---
## 14. IPC Protocol Definition (Rust ↔ Python)

As of Phase 6.1, Velo has transitioned from structural JSON to **MessagePack over Length-Prefix Framing** for high-performance cross-process communication.

### 14.1 Wire Format
The protocol uses a fixed-size header followed by a binary payload:
- **Header**: 4-byte little-endian `u32` (Total Payload Length).
- **Magic**: 4-byte ASCII `VELO`.
- **Version**: 1-byte protocol version (0x01).
- **Payload**: MessagePack-serialized data.

### 14.1.1 The Magic Handshake (DEF-61-004)
To prevent hanging on incompatible or stale sockets, Velo implements a **Magic Handshake** during every connection initiation:
1. **Host (Rust)** sends `VELO` + `0x01`.
2. **Daemon (Python)** verifies the magic and version.
3. If valid, the Daemon sends its own `Handshake` response including `capabilities` (e.g., `preload:ready`).
4. If invalid, the Daemon immediately closes the connection, allowing the Host to fail-fast or clean up the stale socket within 100ms.

### 14.2 `ZygoteCommand` (Host → Daemon)
The CLI sends commands as binary objects:
- `Fork`: Requests worker spawn with specific context (`script_path`, `fast_mode`, `bundle_path`, `stdout_path`).
- `Status`: Requests PID and preload list.
- `Shutdown`: Graceful termination.

### 14.3 `ZygoteResponse` (Daemon → Host)
The Daemon responds with MessagePack:
- `Ready`: Initial handshake.
- `Forked`: Returns `worker_pid` and `exit_code`.
- `Status`: Returns metadata.
- `Error`: Returns failure diagnostic.

### 14.4 Performance & Security
- **Optimization**: Transitions to MessagePack eliminate the ~1ms JSON parsing tax per worker fork.
- **Guard**: All readers enforce a `MAX_MESSAGE_SIZE` (1MB) to protect against fragmentation/DoS attacks.

---
## 15. The 'Enum Deserialization' Trap (2026-01-04)

During the migration from JSON to MessagePack, a critical cross-language schema mismatch was identified in the Rust-to-Python bridge.

### 15.1 The Defect
- **Observation**: Python Zygote failed with `'list' object has no attribute 'get'`.
- **Finding**: While JSON always produces maps for internally-tagged Rust enums (`{"type": "Ready"}`), the MessagePack implementation (`rmp-serde`) may serialize unit variants as a `list` or `str` depending on the tag/content configuration.
- **Remediation**: 
    - **Rust**: Ensure all `ZygoteCommand` and `ZygoteResponse` variants are serialized as maps to preserve the `type` tag property access.
    - **Python**: Defensive decoding in `_recv_command` to handle potential list-wrapped payloads.

### 15.2 Remediation: Smart Unpacking
A defensive `_smart_unpack` method was added to `ZygoteServer` in Python to normalize MessagePack behaviors:
- **Unit Variants**: Converted from simple strings/lists (`"Ready"` or `["Ready"]`) to `{"type": "Ready"}`.
- **Struct Variants**: Converted from **positional arrays** (`["Fork", script_path, args, ...]`) to full dictionaries by mapping indexes to known field names.

### 15.3 Conclusion
Cross-language binary IPC requires explicit synchronization of the **positional schema** if the Rust serializer defaults to compact array formats for enums.

---
## 16. Robust Fallback & CI Pathing (ADV-3)

To ensure high availability in production and CI environments where high-performance C-extensions (`msgpack`) may be absent or incompatible, Velo implement a multi-tiered fallback discovery engine.

### 16.1 Search Hierarchy
When the primary C-extension fails to load, the Zygote daemon searches the following locations for the vendored `umsgpack` library:
1. **Module Relative**: `../python/velo/_vendor/` (Standard source layout).
2. **Project Root**: `./python/velo/_vendor/` (Local development/tests).
3. **Execution Relative**: `./_vendor/` (Installed package layout).

### 16.2 Invariant: "Existing > Fast"
This strategy ensures that the Zygote remains functional (falling back to pure-Python serialization) even in minimal environments, while notifying the user via a stderr diagnostic to install the optimized binaries.

---
## 17. The '30s Timeout' Regression (2026-01-04)

Immediately following the merge of Phase 6.1, a P0 performance regression was identified in the **benchmark loop**.

### 17.1 Observation
While standard execution works, the `scripts/benchmark_startup.sh` reports a **30,038ms (30s) warm start**. This effectively negates the speedup (0.0x).

### 17.2 The Diagnostic Signal
Zygote logs correlate this latency with the **pure Python MessagePack fallback**:
`⚠️ Warning: fast 'msgpack' extension failed to load. Falling back to pure Python implementation.`

### 17.3 Known Issue: Handshake Deadlock
There is a high-probability hypothesis that the pure Python implementation (`umsgpack.py`) or the `_smart_unpack` logic is interacting poorly with the **4-byte length-prefix framing**. 
- **Impact**: Zygote becomes a liability rather than an asset until resolved.

### 17.4 Forensic Trace (Ritual 44)
Analysis of the Zygote debug logic (`/tmp/velo-zygote-debug.log`) proves the IPC messages are exchanged, but timing is critical:
1. **Zygote Log**: `[velo-zygote] Waiting for worker PID: 92232 (sync)`
2. **IPC RECV**: Received `Fork` command at `17:46:22.063`
3. **IPC SEND**: Sent `Forked` response at `17:46:22.074`
Despite this 11ms turnaround in the logs, the CLI times out at 30,000ms. **This was due to a protocol version mismatch with a stale background process.**

## 18. Resolution: Protocol Version Socket Isolation (2026-01-04)

To resolve the 30s timeout permanent, Velo now uses versioned socket paths with mandatory user isolation.

### 18.1 User-Isolated & Versioned Paths
- **Pattern**: `$TMPDIR/velo-{UID}/zygote-v{PROTOCOL_VERSION}.sock`
- **Rationale**: Isolates older Zygote processes from newer CLI binaries and prevents cross-user interference on shared systems.
- **Security**: The directory is created with `0700` permissions.
- **Benefit**: Upgrading Velo will automatically trigger the start of a compatible Zygote daemon rather than hanging on a stale one (Ref: DEF-61-004).

### 18.2 Connection-Aware Cleanup
- Instead of simple deletion, the launcher now performs a `UnixStream::connect` test with a 100ms timeout.
- Sockets are only removed if the connection fails (truly stale).
- If the connection succeeds, the CLI warns the user of an incompatible version conflict.

## 19. Implementation Best Practices (DEF-61-004)

Standardized safeguards for Unix domain socket management:

### 19.1 Permission Enforcement
- **Standard**: Directory must be `0700` (user-only).
- **Hardening**: Use `fchmod` or `std::fs::set_permissions` immediately after creation to bypass `umask` interference.
- **Verification**: Always verify the set mode matches `0700` before binding the socket.

### 19.2 Path Length Limit (108 Chars)
- **Constraint**: Unix sockets have a rigid 108-character limit.
- **Problem**: macOS `$TMPDIR` can be deeply nested, leading to truncation errors.
- **Solution**: Implement a path length check. If `preferred_path.len() > 108`, fall back to the root `/tmp/velo-{UID}/` directory.

### 19.3 Graceful Cleanup
- Avoid CLI crashes on permission errors during stale socket cleanup.
- If a socket exists but is owned by another process (or user), log a warning but continue startup execution.

## 20. QA Requirements Matrix (EF-61-004)

Verification of the systematic fix requires 17 test cases across 4 categories:

| Category | Cases | Focus |
|:---|:---:|:---|
| **Core** | 5 | Version isolation, user isolation, basic cleanup. |
| **Edge** | 5 | Deep paths (>80 chars), permission conflicts, concurrent start. |
| **Regression** | 4 | v0.6.1 → v0.6.2 upgrade/downgrade matrix. |
| **Performance** | 3 | Latency of discovery (<1ms) and cleanup (<100ms). |

**Acceptance Criterion (AC-11)**: Socket connection latency for warm-start handover must remain **< 5ms**.

---
## 21. Phase 6.1.1: Zygote Worker Integration (RFC-0011)

As of Phase 6.1.1, Velo has addressed a critical gap where uvicorn/gunicorn workers were bypassing the Zygote's pre-warmed state by spawning their own subprocesses via `multiprocessing.spawn`.

### 21.1 The Composition Architecture (Option C)
To maximize performance while minimizing integration complexity, Velo implements a composition-based ownership model:
- **Velo Supervisor**: Manages the worker pool (restart, scale, health).
- **Zygote fork()**: Every worker is forked directly from the Zygote parent.
- **ASGI Execution**: Each forked worker executes `uvicorn` in single-worker mode (`--workers 1`).
- **Result**: Cold start drops from **~200ms** to **<20ms** per worker.

### 21.2 Shared Resource Efficiency
Because workers are forked from a pre-warmed Zygote, they inherit:
1. **Executed Bytecode**: Modules are already in memory.
2. **COW Memory**: Workers share the majority of their memory footprint with the parent Zygote until mutation occurs.
3. **Open Handles**: Shared underlying system descriptors where applicable.

### 21.3 Architectural Implementation: Unique Authority Routing
Post-integration verification (2026-01-05) confirmed the successful use of **Unique Authority Mapping** for UDS connection pooling:
- **The Solution**: The Rust L7 Proxy generates a unique URI authority for each worker (e.g., `http://worker-1@velo`).
- **Connection Pooling**: Since Hyper's connection pool keys by authority, this ensures that each UDS worker maintains its own persistent connection pool, even though they share the same protocol scheme.
- **Protocol**: All internal communication is now strictly MessagePack over AFD_UNIX (Unix Domain Sockets), eliminating TCP overhead and port collisions.

### 21.4 Post-Fork Hygiene Protocol (Industrial Standard)

To ensure industrial-grade security and reliability, every worker forked from the Zygote MUST execute a deterministic re-initialization sequence via `post_fork_reinit()` before accepting traffic.

| Order | Action | Purpose |
| :--- | :--- | :--- |
| **1** | **FD Cleanup** | Whitelist-based closure of inherited file descriptors to prevent leaks. |
| **2** | **PRNG Reset** | Call `random.seed()` + `numpy.random.seed()` to prevent sequence collision. |
| **3** | **SSL/Crypto** | Re-initialize SSL context (`ssl.create_default_context`) to avoid duplicate nonces. |
| **4** | **Signal Reset**| Reset all handlers to `SIG_DFL` & reset `set_wakeup_fd(-1)` to purge asyncio pollution. |
| **5** | **HPC Restore** | Restore `OMP_NUM_THREADS` (HPC thread count) to match worker resource quotas. |

> **Core Principle**: High standards, strict requirements. RFCs are organizational assets.

## 22. Future Architecture: Native ASGI Runtime Evolution Path

To further eliminate per-worker overhead (Python event loop + HTTP parsing in every worker), the architectural roadmap includes a transition to a **Rust-Native Frontend**:

```text
Rust HTTP Server (hyper/axum)
├── Accept all HTTP connections (High performance)
├── Load balance across workers (Round-robin)
└── Workers 1-N (ASGI processing only)
    ├── Forked from Zygote
    └── Communicate via Unix Domain Sockets or Shared Memory
```

### 22.1 Industrial Design Mandates
- **IPC-Native Port Management**: Transition from TCP (`AF_INET`) to **Unix Domain Sockets (`AF_UNIX`)** for all internal worker communication. This eliminates port-collision risks and hardens the security perimeter.
- **Deep Process Supervision**: Velo acts as the direct supervisor for all forked workers, eliminating middle-man process managers (like Uvicorn's parent) to ensure direct Zygote inheritance.
- **Shared Memory Metrics**: Implement Prometheus-style metrics in shared memory for zero-IPC observability of worker health.
- **Rolling Restarts**: Enforce zero-downtime updates with health-check verified pool swaps.

---

## 23. Application Gateway: L7 Proxy Blueprint (2026-01-05)

To implement the "Future Architecture" (Option A), Velo introduces a high-performance **Rust-native L7 Proxy** that replaces the standard Uvicorn/Gunicorn socket management.

### 23.1 Key Components
- **UdsConnector**: Enables `hyper` to communicate with workers over Unix Domain Sockets using the `ConnectionGuard` for lifecycle tracking.
- **Least-Connections LoadBalancer**: Atomic tracking of active worker connections using `AtomicUsize`.
- **VeloProxyService**: Rewrites requests, injects RFC-standard headers (`X-Forwarded-*`), and handles W3C Trace Context propagation.
- **Socket Hygiene**: Automated `unlink()` guards and support for **Abstract Namespace Sockets** (Linux only) to ensure clean bindings.
- **Connection Persistence**: Integrated `hyper-util` legacy client with custom resolver to enable connection reuse over UDS.

---

## Appendix O: Strategic Discovery & Execution Traps

### O.0 Related Documents
- [RFC Master Record](./rfc_master_record.md)
- [Zygote Master Guide](./zygote_master_guide.md)
- [UDS Client Recovery Strategy](../design/uds_client_recovery_strategy.md)
- [Q1 2026 Strategy](../strategy/q1_2026_sandwich_strategy.md)

### O.1 Environment Discovery Hierarchy
Velo follows a strict priority chain to ensure dependencies are loaded from the correct context:
1. **Local `.venv` Directory**: Highest priority. Prevents global environment pollution.
2. **`VIRTUAL_ENV` Env Var**: Respects the active terminal's `activate` state.
3. **`VELO_PYTHON` Env Var**: Explicit developer override.
4. **System Python**: Final fallback.

### O.2 AST-based Discovery
Velo uses the `ast` module to locate application objects without execution:
- **Instance Search**: Scans for `FastAPI`, `Starlette`, or `Flask` global assignments.
- **Factory Pattern**: Identifies `create_app()` or similar function returns.

### O.3 The `exec()` and `atexit` Trap
When running user code via `exec()` inside a wrapper process:
- **The Problem**: Standard `atexit` handlers are often bypassed or ignored.
- **The Solution**: Velo's runner MUST explicitly trigger cleanup/flush functions (e.g., for profiling data) in a `finally` block to ensure data persistence.

---
---

## 24. Shadow Preloading (Optimization C-Prime)

Velo's Zygote process achieves fast worker spawning by pre-loading heavy Python libraries. However, the time taken to import and execute these libraries (the "Framework Execution Gap") can still take upwards of 400ms.

**Shadow Preloading** decouples socket availability from library initialization.

### 24.1 Architectural Design
The Python Zygote (`velo_zygote/main.py`) introduces a `preload_state` state machine:
- **STARTING**: Initial state upon process launch.
- **LOADING**: Socket is bound and listening, but libraries are still being imported in a background thread.
- **READY**: preloading is complete; forking is now O(1).

### 24.2 Non-Blocking Socket Availability
The `ZygoteServer.start()` method initiates the Unix Domain Socket (UDS) server immediately. It then triggers `_preload_modules()` as an asynchronous background task using `asyncio.run_in_executor`.

### 24.3 The Fork Queue (Graceful Buffering)
If the Zygote receives a `Fork` command while in the `LOADING` state, it appends the request to an internal `fork_queue`. As soon as the state transitions to `READY` (signaled via an `asyncio.Event`), the `_process_fork_queue()` method executes all pending forks.

### 24.4 Performance Impact

| Scenario | Startup Latency (CLI visibility) | Worker Spawn Speed |
| :--- | :--- | :--- |
| **No Preloading** | ~100ms | ~500ms (Cold) |
| **Sync Preloading** | ~600ms | ~40ms (Warm) |
| **Shadow Preloading**| **~150ms** | **~40ms (Warm)** |

### 24.5 Protocol Handshake (Capabilities)
The "Magic Handshake" (VELO v0.1) conveys preloading status:
- `capabilities: ["preload:loading"]` -> Zygote is up but still warming.
- `capabilities: ["preload:ready"]` -> Zygote is fully optimized.

When operating worker pools via the L7 Proxy, the Zygote parent process exhibits "Ephemeral" behavior that can impact diagnostic tools and lineage auditing.

- **The Pattern**: The `ZygoteServer` (Python) spawns the requested number of workers and ensures they have reached a "Ready" state (bound to UDS). Once the workers are autonomous, the Zygote parent may receive an `Interrupted` signal or transition to a background management state that is difficult to detect via standard `ps` or `pgrep` if checked slightly too late.
- **Root Cause (Hypothesis)**: The Velo supervisor (Rust) may be signaling the Zygote process to enter a low-power or "quiet" state once initial forking is done, or the Python Zygote's signal handler for `SIGINT` is overly aggressive during the transition to worker management.
- **Diagnostic Trap**: In Tier 0 smoke tests, this often results in `Zygote process not detected` errors despite the workers and the proxy functioning perfectly.
- **Verification Requirement**: Lineage verification (Worker PPID == Zygote PID) must be performed **immediately** after the workers are spawned, or tools must be configured to account for the Zygote's rapid transition/shorter resident lifespan compared to the long-lived workers.

## 25. Troubleshooting: Protocol Type Mismatches

During worker shutdown or status checks, a specific IPC protocol error may manifest:

- **Error**: `⚠️ Protocol error: invalid type: unit value, expected u32`
- **Context**: Occurs during command responses, most notably for `WaitWorker`.
- **Cause**: The Rust supervisor expects a numeric status code (`u32`), but the Python Zygote returns a `None` (unit value) in the MessagePack response.
- **Resolution**: Both `velo_zygote/main.py` and the test fixtures were updated to ensure strict type compliance. The Python side now explicitly returns numeric values (like `0`) instead of `None` for all fields mapping to numeric types in the Rust `ZygoteResponse` enum.

## 26. Diagnostic Best Practices: Stale Log Traps

When debugging the Zygote's ephemeral lifecycle, logs are the primary source of truth, but they can be deceptive.

- **The Trap**: If a new server instance fails to start (e.g., due to a port conflict or binary error) before it can initialize its logger, a `tail -n 20` command on the log file will return the **output of the previous successful run**.
- **Detection**: Check if worker PIDs or timestamps are identical across multiple test runs. If they are, you are likely looking at stale data.
- **Remedy**: Always clear or rotate the log file (`rm ~/.local/state/velo/zygote.log`) or use a unique session-based log path before starting the server in a diagnostic loop.

## 27. Zygote Lineage Auditing Standards

Verifying process lineage in Zygote environments is mandatory for all Tier 0 smoke tests and architectural audits.

### 27.1 The Auditing Challenge
1. **The setsid() Paradox**: The Zygote supervisor often calls `setsid()` to detach. Standard tree traversal may fail if checking from the original root.
2. **The Clone Army Trap**: Forked workers inherit the command line of the Zygote supervisor. Searching for "uvicorn" will return 0 results.

### 27.2 Standard: Lineage-Based Detection
Process identification MUST NOT rely on `cmdline` alone. Use the following logic:
- **Zygote Supervisor**: A process with the Zygote entry point whose parent is NOT another Zygote process.
- **Worker**: A process with the Zygote `cmdline` whose parent IS the detected Zygote Supervisor.
- **Refinement for setsid()**: In environments using `setsid()`, the PPID might initially point to the launcher but can be re-parented. The robust check identifies the supervisor as the "top-most" Zygote process in the tree (the one whose parent doesn't match the Zygote signature). Workers are confirmed as descendants.

---
## 29. Audit Remediation Patterns (Phase 6.1.1)

To resolve the "Fatal Wounds" identified in the Phase 6.1.1 Independent Audit, the following architectural patterns were institutionalized.

### 29.1 Pattern: The Supervisor Guardian (Anti-Orphan)
**Vulnerability**: Workers or Zygotes persist as orphans if the Rust supervisor is killed with `SIGKILL`.
**Remediation**: 
- Zygote process starts a daemon thread in `ZygoteServer.start` using `WorkerRegistry.start_guardian(os.getppid(), 0)`.
- The thread polls every **1 second**.
- If `os.getppid() != original_parent_pid`, it executes `os._exit(1)` immediately.

### 29.2 Pattern: Forced RAII Guard (Anti-Shadow Trap)
**Vulnerability**: Existing Zygote detection lacks a reference-holding guard, leading to silent fallback.
**Remediation**:
- In `src/serve/runner.rs`, the `_zygote_guard` is populated even if `socket_path.exists() == true`.
- Code: `_zygote_guard = Some(ZygoteLauncher::new(socket_path))`.
- **Active Handshake**: A `ZygoteCommand::Handshake` is sent to verify that the existing socket is responsive and protocol-compliant, preventing 30-second timeouts.

### 29.3 Pattern: Lock Contention Remediation (Mutex Migration)
**Vulnerability**: `RwLock` writer starvation or deadlocks on specific platforms (macOS) during high-frequency health polling.
**Remediation**:
- Migrated `lb_holder` (LoadBalancer reference) from `RwLock` to `std::sync::Mutex`.
- Switched from opportunistic read/write locking to a single exclusive lock for stability under heavy probe load.

### 29.3 Pattern: Protocol Standardization (Anti-Desync)
**Vulnerability**: IPC desync due to serialization mismatches (Arrays vs. Maps) across Rust and Python, leading to buffer errors and brittle handshakes.
**Remediation**:
- **Pure Map Protocol**: Velo enforces a single, standardized **Map-based protocol** using MessagePack. This improves observability and simplifies the control plane.
- **Rust Enforcement**: Uses `#[serde(tag = "type")]` and `Serializer::new().with_struct_map()` to ensure every message is a tagged map.
- **Python Enforcement**: The `CommandRouter` exclusively accepts dictionaries. This eliminates the need for complex positional index mapping (`_list_to_dict`) and allows the code to follow a "One Source of Truth" approach for commands.
- **Fail-Fast**: Any message not matching the expected map format results in an immediate protocol error rather than a silent failure or partial parse.

### 29.4 Pattern: Signal-Loop Safety
**Vulnerability**: `SIGCHLD` handlers triggering `asyncio` tasks can cause race conditions or loop errors if not executed safely.
**Remediation**:
- **Loop-Safe Delivery**: Implementation using `loop.call_soon_threadsafe()` to schedule the `_async_reap` task.
- **Robust Registration**: Signal registration wrapped in `try-except` for compatibility with non-main-thread execution environments.

### 29.4 Pattern: Emergency Worker Reaper
**Vulnerability**: Shutdown command or timeout leaves worker processes alive in memory.
**Remediation**:
- `WorkerRegistry` implements a `kill_all()` method using `os.kill(pid, 9)`.
- `ZygoteServer` calls `kill_all()` in the `finally:` block of its `start()` method, ensuring no worker survives the Zygote process.

### 29.5 Pattern: The Shadow Trap Diagnostic
**Vulnerability**: A stale Zygote process running on a reused Unix Domain Socket.
**The Signal**: `warn: Zygote pre-warm failed: Failed to start Zygote: Deep probe PID mismatch: got 628, expected 621 (Shadow Trap detected!)`
**Forensics**:
- When the Rust supervisor (`velo serve`) performs its startup handshake, it doesn't just check if the socket exists; it performs a "Deep Probe."
- It queries the responding Zygote for its PID.
- If the PID returned by the socket does not match the child PID just spawned by the supervisor, a **Shadow Trap** is declared.
**Remediation**: 
1. The supervisor immediately aborts the pre-warm attempt and falls back to standard uvicorn spawning to ensure service availability.
2. The user is warned that a ghost Zygote exists.
3. Cleanup involves a precise kill of the ghost PID (using the "got {PID}" value from the log).

---
## 30. Phase 6.1.1 Industrial Remediations (2026-01-06)

To achieve the **FULL PASS** verdict for Golden Path E2E tests, the following technical fixes were applied:

### 30.1 Atomic Load Balancer Fix (GOLD-002)
- **Defect**: Round-robin state desync across concurrent proxy threads.
- **Resolution**: Ported `LoadBalancer` counter to `Arc<AtomicUsize>`.
- **Impact**: Guaranteed distribution across all workers, passing the single-worker pinning check.

### 30.2 Unified Zygote Path (GOLD-003)
- **Defect**: L7 Proxy (and header injection) was bypassed for single-worker loads (`workers=1`).
- **Resolution**: Ported the supervisor logic to mandatory entry into the Zygote/L7-Proxy path when `--use-zygote` is requested, regardless of worker count.
- **Impact**: Consistent `X-Forwarded-For` injection across all service scales.

### 30.3 Stale Socket Garbage Collection
- **Self-Healing**: The Rust supervisor now proactively checks the liveness of existing Zygote sockets and handles protocol handshakes during startup.
- **Logic**: If a socket exists but is not responding (`!ipc::is_socket_alive(path)`), it is explicitly unlinked before attempted startup.
- **Benefit**: Prevents the "Shadow Trap" where stale UNIX sockets cause silent fallback to non-Zygote mode.

### 30.4 Test Environment Isolation
- **Ritual**: Isolation via `VELO_ZYGOTE_SOCKET` environment variable.
- **Practice**: E2E test fixtures now generate unique socket paths within the `tmp_path` to prevent cross-test interference.

### 30.5 Worker Socket Partitioning (Architectural Defect)
- **The Defect**: `WORKER_COUNTER` in `src/serve/worker.rs` is a process-local `AtomicU64`. When running multiple `velo serve` instances concurrently (e.g., in a parallel test suite), different processes would all try to bind the same global paths: `/tmp/velo-worker-0.sock`, `/tmp/velo-worker-1.sock`.
- **The Resolution**: Ported worker socket path generation to include the parent Zygote's PID: `/tmp/velo-worker-{PID}-{ID}.sock`.
- **Impact**: Zero-collision parallel integration testing.

### 30.6 EnvShield Expansion (Pillar 1)
- **Problem**: Strict environment cleansing caused `ImportError` in workers because `VIRTUAL_ENV` and `PYTHONPATH` were stripped.
- **Resolution**: Expanded the Mandatory Whitelist to include Python toolchain context and Locales.
- **Strategic Note**: Security must not break established developer workflows (e.g., `uv`, `conda`).

### 30.7 Sandbox-EnvShield Synchronization
- **Problem**: Pillar 3 (Sandbox) wrapping used a separate `Command` object that didn't automatically inherit the Pillar 1 (Env) whitelisting logic.
- **Resolution**: Explicitly synchronized whitelisting and HPC thread guards between the base Python command and the `sandbox-exec` wrapper.

---

## 31. Forensic Stability Registry (Jan 2026)

| ID | Issue | Symptom | Status |
| :--- | :--- | :--- | :--- |
| **STB-611-001** | Tool-chain Strictness | `uv run` failure due to missing `project.name`. | **Closed** (Operational Note) |
| **STB-611-002** | Sandbox Overhead | 30s Timeout on macOS integration tests. | **Open** (Calibration Required) |
| **STB-611-003** | Respawn Death Spiral | Workers dying immediately under proxy pressure. | **Open** (Potential Race) |
| **STB-611-004** | Socket Path Depth | truncation on macOS `$TMPDIR`. | **Fixed** (104-char threshold) |

## 32. Industrial Security: The 4 Pillars of Zygote Hardening (Pillar 1 to 4)

To achieve enterprise-grade security for the Zygote process tree, Velo implements four complementary layers of isolation ("Full Armor").

### 32.1 Pillar 1: Env Isolation (EnvShield)
- **Strategy**: Rust-enforced environment whitelisting.
- **Implementation**: The `ZygoteLauncher` in Rust clears the environment and explicitly passes only a safe subset of variables (e.g., `PATH`, `HOME`). It also injects high-performance guards (`OMP_NUM_THREADS="1"`) and Python-specific isolation flags.
- **Result**: Proved successful by `test_PILLAR_1_env_isolation`.

### 32.2 Pillar 2: Import Isolation (ImportShield)
- **Strategy**: Python-level `MetaPathFinder` kernel shield.
- **Implementation**: Blocks user scripts from importing internal `velo_zygote` modules and prevents framework modules from shadowing user scripts of the same name.
- **Result**: Proved successful by `test_PILLAR_2_import_shield`.

### 32.3 Pillar 3: OS Sandboxing (SandboxShield)
- **Strategy**: Platform-specific OS sandboxing policies.
- **macOS (Seatbelt)**: Enforces `sandbox-exec` with a profile allowing only project-local and necessary system paths.
- **Linux (Namespaces)**: Implements `unshare(CLONE_NEWNET)` and `PR_SET_NO_NEW_PRIVS`.
- **Signaling**: Unauthorized filesystem writes trigger an immediate OS signal (e.g., SIGHUP, SIGKILL), which Velo's test suite and supervisor correctly identify as a successful security block.
- **Result**: Proved successful by `test_PILLAR_3_sandbox_write_denial`.

### 32.4 Pillar 4: Scope Isolation (ScopeShield)
- **Strategy**: Holistic Defense in Depth.
- **Implementation**: The combination of OS sandboxing, environment cleansing, and import shielding ensures that even if a vulnerability exists in the Python interpreter or the framework, the attacker is trapped in a non-networked, read-only filesystem with no access to system credentials.
- **Status**: Formally verified in Phase 6.1.1, but currently impacted by the macOS connection regression.

- **The Symptom**: "Address already in use" errors during worker startup or "404 Not Found" crosstalk where a proxy from one test talks to a residual worker from another.
- **The Discovery**: Identification of this "Local Counter Trap" was a key breakthrough in mapping the 404 ghosting in non-sequential runs.
- **The Resolution**: **Sibling Socket Strategy**. Worker sockets MUST be generated relative to the Zygote socket's directory to ensure isolation across concurrent `velo serve` instances. Verified in Phase 6.1.1.
- **Known Regression (Round 17)**: On macOS, the final "Prosecutor" run (Step 2219) confirmed that while Security Pillars are functional, the integration of the mandatory L7 Proxy and hardening triggers **Timeout Regressions** in Level 1 features. Certified as **SECURITY CERTIFIED / INTEGRATION REJECTED (macOS)**.

---
## 33. Phase 6.1.1 Audit Trail & Verification Matrix

### 33.1 Implementation History
- **Round 1 (Baseline Collapse)**: Rejected (62% failure).
- **Round 4 (Stabilization)**: Resolved FD Hygiene and finalized **Surgical Path Sanitization**.
- **Round 16 (Success Ritual)**: Implemented "Full Armor" security and correctly ported the L7 Proxy for `workers >= 1`. Achieved 11/11 PASS in Round 16 test cycle.
- **Round 17 (Prosecutor Audit)**: Regression unmasked on macOS. Mandatory proxying for single workers in a hardened environment causes connection timeouts in L1 Feature tests, despite Security Pillars passing.

### 33.2 Requirement Compliance Matrix (Phase 6.1.1)

| Feature | Domain | Test Case | Status |
|:---|:---|:---|:---|
| **Worker Respawn** | Stability | `test_WB_006_worker_respawn` | ✅ VERIFIED |
| **App Affinity** | Security | `test_WB_004_cross_app_affinity` | ✅ VERIFIED |
| **Pillar 1: EnvShield**| Security | `test_PILLAR_1_env_isolation` | ✅ VERIFIED |
| **Pillar 3: Sandbox** | Security | `test_PILLAR_3_sandbox_write` | ✅ VERIFIED |
| **Features L1-1...L1-6**| Integration| `test_L1_X_...` | 🔴 TIMEOUT |

**Final Auditor Verdict**: 🟠 **SECURITY CERTIFIED / INTEGRATION REJECTED (macOS)**. The "Full Armor" architecture is logically and securely sound, but integration timeouts have rendered the functional features unstable on macOS.

## 34. Zygote Stability & Recurrent Failures (2026-01-06)

Ongoing industrial verification has revealed two high-priority stability issues regarding concurrent testing and crash recovery.

### 34.1 PID Cross-Talk In Concurrent Suites
- **Defect**: E2E tests picking up Zygote processes from other parallel tests.
- **Remediation**: Updated `conftest.py` detection logic to strictly filter by the assigned `VELO_ZYGOTE_SOCKET` path.
- **Impact**: Zero-crosstalk in parallel CI runs.

### 34.2 The Recovery Death Spiral (GOLD-006)
- **Defect**: Zygote supervisor crash (`Connection refused`) after multiple worker crashes.
- **Root Cause**: **Asyncio Event Loop Race**. The Zygote's `SIGCHLD` handler schedules reaping tasks via `loop.call_soon_threadsafe`. If worker deaths occur during supervisor shutdown or state transitions, the loop may close before the task executes, raising `RuntimeError: asyncio.get_event_loop() stopped`.
- **Status**: **EVIDENCE SOLIDIFIED**. Pinned as a critical architectural failure for Developer remediation.

### 34.3 Log Diagnostic Methodology
- **Standard**: Always check `~/.local/state/velo/zygote.log` first.
- **Trap**: Stale logs from previous runs. Mandatory ritual: Clear logs between forensic cycles to ensure trace accuracy.

---
## 35. Architectural Guardrails (Non-Modifiable)

### 35.1 The Zygote Proxy Mandate
- **Mandate**: In Zygote mode, the L7 Proxy MUST be activated for all worker counts ($N \ge 1$).
- **Logic**: Enforced in `src/serve/runner.rs` via `workers >= 1`.
- **Purpose**: Ensures consistent identity (XFF injection) across dev and prod deployment scales.
- **Rule of Non-Modification**: This is a **Permanent Architectural Guardrail**. It MUST NOT be modified or reverted to `> 1` unless Real-IP injection is re-engineered at a lower level.

### 35.2 AI Agent Safety: The pkill Ritual
- **Finding**: Documented IDE crashes caused by `pkill -f` on Velo processes.
- **Standard**: All background agents and developers MUST use **Exact Pattern Matching** (`pkill -x velo`) or track PIDs specifically.
- **Mitigation**: Broad-spectrum substring matching in shared IDE environments is FATAL and causes session collapse.

---
---

## 36. Zygote Protocol: Handshake & Shutdown Calibration (2026-01-06)

Industrial verification of the "Full Armor" suite on macOS identified critical latency patterns in the Zygote's lifecycle management.

### 36.1 The 'WaitWorker' Shutdown Timeout (DEF-611-029)
The `WaitWorker` command occasionally times out during supervisor shutdown, even if the worker eventually exits with code 0.
- **Root Cause**: Potential congestion in the Zygote's `asyncio` loop or macOS Sandbox audit overhead during process termination.
- **Trace Signal**: `[IPC SEND] WaitWorker ...` followed by `Timeout reached. FAILED`.
- **Management Protocol**: Supervisors MUST increase the `wait_timeout` to **15s+** for worker shutdown in hardened environments.

### 36.2 Handshake Strategy: The 'Preload:Loading' State
Modern Zygotes report their internal readiness state during the initial handshake.
- **Capability `preload:loading`**: Indicates that framework modules (FastAPI, etc.) are still being imported in the background.
- **Standard**: Rust supervisors MUST wait for the Zygote to report `preload:ready` or poll the `Status` command until the module list is populated before sending the first `Fork` request. Attempting to fork during the `loading` phase results in non-deterministic "Incomplete Module Context" in children.

### 36.3 Hardened Verification Timeouts (macOS Calibration)
To accommodate the increased overhead of the L7 Proxy + Seatbelt Sandbox + EnvShield, the following timeouts are standard for Phase 6.1.1+:

| Operation | Timeout (Hardened) | Rationale |
| :--- | :--- | :--- |
| **Server Ready** | 30.0s | Buffers proxy listener and Zygote module pre-warming. |
| **Worker Fork** | 5.0s | Accounts for Seatbelt kernel audit delay. |
| **WaitWorker** | 15.0s | Ensures the reap future resolves before timeout. |

---

**Last Updated**: 2026-01-06  
**Status**: 🟠 **FUNCTIONAL RECOVERY PROGRESS (macOS)**.  
**Tagline**: High standards, strict requirements. Built with Rust ❤️ to accelerate Python.
