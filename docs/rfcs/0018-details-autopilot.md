# Detailed Design: RFC-0018 (Integrated Custody)

This document specifies the architectural implementation details for the Integrated Custody phase, focusing on Autopilot heuristics and toolchain metadata management.

## 1. Zygote Autopilot Heuristics

The Autopilot system replaces manual `--zygote` flags with architectural intelligence.

### 1.1 Static Analysis Trigger (SAT)
Velo performs a high-speed AST scan (using `ruff` or a custom `syn`-based parser if integrated) to detect "Gravity Modules".

| Module | Trigger Weight | Action |
|--------|----------------|--------|
| `torch` | 1.0 (Critical) | Auto-start Zygote |
| `pandas` | 0.8 (Heavy) | Auto-start Zygote |
| `tensorflow` | 1.0 (Critical) | Auto-start Zygote |
| `transformers` | 0.9 (Heavy) | Auto-start Zygote |
| `numpy` | 0.5 (Medium) | Start Zygote if > 2 instances detected |

### 1.2 Performance-Based Trigger (PBT)
Velo tracks the "Cold Start Overhead" in a local cache (`~/.velo/telemetry.db`).

*   **Logic**: If `bootstrap_latency_ms > 500ms` for 3 consecutive runs, the script is tagged with `AUTO_ACCELERATE=true`.
*   **Decay**: If the script is modified, the PBT state is reset.

---

## 2. Embedded Toolchain Metadata (`uv_metadata.json`)

To ensure integrity and prevent drift, the extracted toolchain is governed by a metadata schema.

### 2.1 Schema Definition
```json
{
  "version": "0.5.x",
  "platform": "macos-arm64",
  "extracted_at": "2026-01-09T12:00:00Z",
  "blake3_integrity": "h...",
  "binary_path": "/Users/user/.velo/bin/uv",
  "is_hermetic": true
}
```

### 2.2 Extraction & Drift Prevention [REMEDIATED OPS-07-001]
1.  **Build-Hash Pathing**: Extracted binaries MUST be stored in `~/.velo/bin/{velo_build_hash}/uv` to prevent toolchain drift when the Velo binary is updated.
2.  **Integrity Check**: Sample first/last 1MB of the binary and verify against `blake3_integrity` if `VELO_STRICT_SEC=1`.
3.  **Sync Logic**: If `version` in metadata != `embedded_version` in Velo binary, trigger **Re-extraction**.

---

## 3. Security Quality Gates

### 3.1 Socket Custody & Atomic Creation [REMEDIATED SEC-07-001]
*   Autopilot MUST use `mkdtemp` (atomic creation) for randomized socket directories to prevent pre-creation race conditions.
*   **Linux (Abstract Namespace)**: On Linux, Autopilot MUST exclusively use **Abstract Namespace Sockets** (e.g., `@velo-zygote-{hash}`). These are filesystem-independent and immune to permission race conditions on `/tmp`.
*   Enforce `0o700` on the socket directory (non-Linux) to prevent cross-user interception.
*   Validate `SO_PEERCRED` (Linux) to ensure only the Velo supervisor connects to the Zygote worker.

### 3.2 Shadow Sync Isolation
*   Shadow `uv sync` operations MUST use `--no-install-workspace` and `--frozen` to prevent side-effects on the user's source tree.
