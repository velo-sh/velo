# RFC-0019: Native Sovereignty (Rust-Native Runtime Engine)

**Status**: DRAFT (Proposed for Phase 7.2)
**Author**: Architect
**Date**: 2026-01-09

## 1. Summary
"Native Sovereignty" replaces the Uvicorn/Gunicorn wrapper with a high-performance Rust host based on Granian principles.

## 2. Key Components
*   **Rust RSGI Host**: Direct L7 management in the Velo binary.
*   **Native Worker IPC**: Optimized FD passing and signal propagation.

## 3. Implementation Target
Phase 7.2 "Native Sovereignty".
