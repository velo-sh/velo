# SPEC-0005: Velo SSOT Master Standard

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-14

## 1. The 0xMaster Axiom
Velo shall maintain a **Single Source of Truth (SSOT)** for all operational and conceptual facts. Any deviation between the Rust Supervisor and the Python Worker is considered a **Fatal Integrity Violation (FIV)**.

## 2. Configuration SSOT (The Transmutation Bridge)
To prevent "Configuration Drift," Velo uses a code-generation pipeline to sync shared constants:

- **Source**: `config/constants.toml`
- **Rust Anchor**: `src/config/generated.rs` (via `build.rs`)
- **Python Anchor**: `velo_zygote/constants.py` (via `build.rs` or specialized script)

**Rule**: Manual hardcoding of magic strings or numeric limits in either Rust or Python is strictly forbidden.

## 3. Environment SSOT (Tiered Sovereignty)
As per **RFC-0023**, the environment is partitioned into immutable tiers:

| Tier | Namespace | Owner | Visibility to App |
|:---|:---|:---|:---|
| **System** | `VELO_SYS_*` | Velo Host | **None** (Hard Scrubbed) |
| **Config** | `VELO_CONF_*` | `pyproject.toml` | Read-only |
| **App** | `VELO_APP_*` | User | Read/Write |
| **Runtime** | `VELO_RUNTIME_*` | Velo Engine | Read-only (Sealed) |

## 4. State SSOT (Forensic Custody)
The persistent state of the Velo environment is anchored at `.velo/env.state`.
- This file is the **Sovereign Evidence** for current binary fingerprints and environment checksums.
- Automated tools MUST consult this state before performing any reconciliation or re-extraction.

## 5. Tooling SSOT (Unified Execution)
- **Rust**: `Cargo` is the sole entry point for system-level logic.
- **Python**: `uv` is the sole entry point for user-space logic and dependency resolution.
- **Velo CLI**: The `velo` binary is the unified frontend that orchestrates both worlds.

## 6. Zero-Drift Invariants
1. **INV-SSOT-001**: Every `VELO_CONF_*` variable must have a corresponding entry in `[tool.velo]` within `pyproject.toml`.
2. **INV-SSOT-002**: Zygote metadata must remain consistent across forking boundaries (Pool Sovereignty).
3. **INV-SSOT-003**: All internal path synthesis (e.g., `PYTHONPATH`) must follow the "Ghost Mode" protocol.
