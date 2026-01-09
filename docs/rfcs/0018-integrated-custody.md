# RFC-0018: Integrated Custody (Seamless Environment & Acceleration)

**Status**: DRAFT (Proposed for Phase 7.1)
**Author**: Architect
**Date**: 2026-01-09

## 1. Summary
"Integrated Custody" transitions Velo into a self-contained AI runtime. It eliminates the "Configuration Gravity" by embedding `uv` and automating the Zygote lifecycle.

## 2. Key Components
*   **Embedded uv**: `include_bytes!` integration for zero-dependency sync.
*   **Zygote Autopilot**: Background daemon management for transparent 50ms cold-starts.

## 3. Implementation Target
Phase 7.1 "Integrated Custody".
