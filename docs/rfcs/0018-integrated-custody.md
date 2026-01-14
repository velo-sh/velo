# RFC-0018: Integrated Custody (Seamless Environment & Acceleration)

**Status**: ✅ IMPLEMENTED (Phase 7.2)
**Author**: Architect
**Date**: 2026-01-09
**Implemented**: 2026-01-12

## 0. Detailed Specifications
*   **Architecture Overview**: [../architecture/velo_uv_architecture_overview.md](../architecture/velo_uv_architecture_overview.md)
*   **Detailed Design**: [0018-details-autopilot.md](0018-details-autopilot.md)
*   **Asset Management**: [../architecture/asset_management_custody.md](../architecture/asset_management_custody.md)
*   **QA Handoff**: [../architecture/handover_qa_phase_7_1_7_2.md](../architecture/handover_qa_phase_7_1_7_2.md)

## 1. Summary
"Integrated Custody" transitions Velo into a self-contained AI runtime. It eliminates "Configuration Gravity" by embedding the `uv` toolchain and automating the Zygote lifecycle. The goal is a **Zero-Config, Zero-Dependency** developer experience.

## 2. Motivation
Currently, Velo requires users to have `uv` installed and manually manage Zygote for performance. This creates friction:
*   **Version Mismatch**: User's `uv` might be incompatible with Velo's expectations.
*   **Cognitive Load**: Users must decide when to use `--zygote`.
*   **Boilerplate**: Manual `uv sync` before running is a DX bottleneck.

## 3. Architectural Blueprint

### 3.1 Embedded Toolchain Lifecycle (The "Custody" Model)
Velo will treat the Python package manager as a private, managed asset.

*   **Asset Embedding**: `uv` binaries for supported platforms (macOS-arm64, macOS-x86, Linux-x86) are embedded into the Velo binary using `include_bytes!`.
*   **Extraction Hierarchy**:
    1.  Check `~/.velo/bin/uv-{hash}`.
    2.  If missing, extract to temporary location, verify BLAKE3 hash.
    3.  Set `0o755` permissions.
    4.  Symlink/Atomic rename to the permanent cache path.
*   **Internal Use Only**: The embedded `uv` is used internally by `velo run` and `velo serve` for environment management.
*   **User Command**: `velo python <args>` provides access to the managed Python environment for scripting and debugging.

### 3.1.1 Configuration (SSOT)
The platform matrix is defined in `config/embedded_assets.toml`:
```toml
[uv]
version = "0.9.24"

[[uv.platforms]]
os = "macos"
arch = "aarch64"
asset_name = "uv-aarch64-apple-darwin"
```

### 3.2 Environment Convergence (The "SSoT" Model)
Velo becomes the Single Source of Truth for the project environment.

*   **Convergence Trigger**: Before execution, Velo computes a fingerprint of `pyproject.toml` and `uv.lock`.
*   **Implicit Sync**: If the fingerprint deviates from the current `.venv` state, Velo executes a shadow `uv sync` transparently.
*   **Test Isolation**: Convergence logic respects the `docs/TEST_ARCHITECTURE.md` isolation invariants.

### 3.3 Zygote Autopilot (The "Acceleration" Model)
Transparent Zygote management based on architectural heuristics.

*   **Heuristic Engine**: 
    - **Static Analysis**: Fast-scanning the target script for `import torch`, `import pandas`, or `from transformers import ...`.
    - **Telemetry**: If a script historically takes > 500ms to boot, mark it for Autopilot.
*   **Shadow Lifecycle**:
    - **Lazy Spawn**: Start Zygote daemon in the background on first "heavy" run.
    - **UDS Custody**: Velo manages the `/tmp/velo-zygote.sock` lifecycle, including automatic cleanup and health checks.

## 4. Impact Analysis
*   **Binary Size**: ~47MB release binary (includes ~29MB embedded `uv`).
*   **DX**: Reduces "Time to First Token" for AI apps from minutes (env setup) to seconds.
*   **Security**: Embedded toolchain reduces TOCTOU risks associated with global `uv` binaries.

## 4.1 Implementation Summary
*   **Phase 1-4**: Core modules (`custody/`), build infrastructure (`build.rs`)
*   **Phase 5**: Asset embedding via `include_bytes!`, BLAKE3 verification
*   **Config**: Declarative platform matrix in `config/embedded_assets.toml`

## 5. Architectural Quality Gates

*   **Gate A (Forensic)**: Embedded `uv` must pass BLAKE3 verification post-extraction.
*   **Gate B (Isolation)**: Autopilot must never pollute the global socket namespace (enforce `0o700`).
*   **Gate C (Performance)**: Shadow `sync` overhead must be < 100ms for no-op cases.

## 6. Strict Security Invariants (RFC-0012 Alignment)
To avoid the "Three Sins" of security (Suffocation, Death Spiral, Collision), Phase 7.1 adheres to:
*   **SEC-ENV-001 (Provenance Guard)**: The embedded `uv` acts as the verified source for all toolchain operations, preventing `LD_PRELOAD` or `PYTHONPATH` hijacking.
*   **SEC-FS-001 (Path Sanitization)**: Extraction and shadow sync use FD-based operations (`openat`) to resist TOCTOU attacks.
*   **Surgical Environment**: Shadow `uv` calls must preserve the Mandatory Whitelist (PATH, VIRTUAL_ENV) while scrubbing the Blacklist (RFC-0012 §3.1).
*   **Atomic Identity**: Extraction paths incorporate the Velo build hash to ensure unique, collision-free workspace identification.

## 7. Alternatives Considered
*   **System uv Integration**: Rejected due to version drift and installation friction.
*   **Conda/Micromamba**: Rejected due to binary size (100MB+) and slower resolution compared to `uv`.

## 8. Technology Radar: Phase 8.x Optimizations

> [!NOTE]
> This section documents future optimizations under evaluation.

### 8.1 Current Limitation: exec() Overhead

The current `uv` integration uses `fork() + exec()`, which has inherent overhead:

| Stage | Time | Optimizable |
|:---|:---|:---|
| **Disk I/O** | ~0.1ms | ✅ OS Page Cache |
| **ELF/Mach-O Parsing** | ~0.5ms | ❌ Kernel |
| **Dynamic Linking** | ~2-3ms | ⚠️ Static linking |
| **Rust Runtime Init** | ~3-5ms | ❌ exec() inherent |
| **Total** | ~7-10ms | Per invocation |

**Note**: `exec()` replaces the process image, so Zygote COW benefits do not apply to `uv` calls.

### 8.2 Phase 8.x: SHM Venv (Memory-Speed Python Environment)

**Goal**: Keep the entire `.venv` in shared memory for memory-speed imports.

```
┌─────────────────────────────────────────────────────────────────┐
│  SHM Venv Architecture                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  /dev/shm/velo-venv/  (Linux)                                    │
│  shm_open("/velo-venv")  (macOS)                                 │
│  CreateFileMapping()  (Windows)                                  │
│       │                                                          │
│       ├── torch/                                                 │
│       ├── pandas/                                                │
│       └── *.so, *.pyc                                            │
│                                                                  │
│  Python: sys.path.insert(0, shm_venv_path)                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Cross-Platform SHM Library Candidates

| Crate | Platform Support | Features | Status |
|:---|:---|:---|:---|
| **`shared_memory`** | Linux, macOS, Windows | Named SHM, cross-process | ⭐ Primary |
| **`memmap2`** | All major platforms | File-backed, COW, exec maps | ⭐ Fallback |
| **`mmap-rs`** | Tier 1 all platforms | Huge Pages, memory locking | 🔮 Research |
| **`mmap-sync`** | Cross-platform | Single-writer multi-reader | 🔮 Research |

#### Platform Equivalence

| Platform | Technology | Path/API |
|:---|:---|:---|
| **Linux** | tmpfs / shm_open | `/dev/shm/`, `/run/` |
| **macOS** | shm_open + mmap | POSIX shm, no filesystem path |
| **Windows** | Memory-Mapped Files | `CreateFileMapping()` API |

#### Benefits

| Aspect | Disk venv | SHM venv |
|:---|:---|:---|
| **import speed** | Page Cache (~ms) | Memory (~μs) |
| **Cross-process sharing** | File locks | Native SHM |
| **Restart persistence** | ✅ Survives | ❌ Volatile |

#### Adoption Criteria (All MUST be met)

1. ✅ Cross-platform abstraction layer implemented
2. ✅ Benchmark shows >50% import speedup for large packages
3. ✅ Fallback to disk venv on SHM failure
4. ✅ Memory pressure detection and eviction policy

### 8.3 Phase 8.x: uv Library Integration (Alternative)

**Goal**: Integrate `uv` as a Rust library to eliminate exec() overhead.

```toml
# Cargo.toml (potential)
[dependencies]
uv-resolver = { git = "https://github.com/astral-sh/uv", tag = "0.5.14" }
uv-installer = { git = "https://github.com/astral-sh/uv", tag = "0.5.14" }
```

| Aspect | Binary Embed (Current) | Library Integration |
|:---|:---|:---|
| **Call overhead** | ~10ms (exec) | ~0.1ms (function) |
| **COW sharing** | ❌ | ✅ |
| **Build complexity** | Low | High (dependency conflicts) |
| **Version decoupling** | ✅ | Lock via Cargo.toml |

**Status**: 🟡 EVALUATION (Blocked on dependency conflict analysis)

