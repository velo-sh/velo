# RFC-0018: Integrated Custody (Seamless Environment & Acceleration)

**Status**: ✅ APPROVED (TITANIUM Grade) — Phase 7.1
**Author**: Architect
**Date**: 2026-01-09

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
*   **Shadow Command**: `velo python ...` and `velo pip ...` will be proxied through the embedded `uv` context.

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
*   **Binary Size**: Anticipated increase of ~15MB (compressed `uv` binaries). 
*   **DX**: Reduces "Time to First Token" for AI apps from minutes (env setup) to seconds.
*   **Security**: Embedded toolchain reduces TOCTOU risks associated with global `uv` binaries.

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
