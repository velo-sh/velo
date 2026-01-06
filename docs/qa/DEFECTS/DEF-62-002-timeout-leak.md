## Defect Report: DEF-62-002

**Severity**: 🟠 HIGH (Performance/Stability)  
**Status**: OPEN  
**Phase**: 6.2 (Kinetic Optimization)  
**Component**: `src/zygote/mod.rs` (Rust)  
**Source**: [RFC-0013 §3.1](../../rfcs/0013-kinetic-protocol.md)

### Description
The 10ms handshake budget is currently applied as a per-operation timeout (e.g., `set_read_timeout` before each receive). This allows a slow or malicious Zygote to stall the CLI for up to 3x the intended budget (Connect + Ready + Handshake + Status).

### Evidence
- **File**: `src/zygote/mod.rs`
- **Audit**: `Whitebox Audit` (2026-01-06)
- **Prosecutor Test**: `tests/qa/test_phase6_2_agent_b_stability.py::test_STAB_621_cumulative_timeout` **FAILED** (Confirmed individual steps pass while total budget is exceeded).

### Recommendation
Update `ZygoteLauncher` to track `Instant::now()` and calculate the `remaining` budget before each IPC operation, setting the socket timeout accordingly.

---
**Reporter**: QA Leader (Agent Antigravity)
