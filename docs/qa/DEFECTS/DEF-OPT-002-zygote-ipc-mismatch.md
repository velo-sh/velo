# DEF-OPT-002: Zygote IPC Protocol Mismatch (P0 BLOCKER)

**Priority:** P0 (BLOCKER)
**Status:** OPEN
**Found By:** QA Leader
**Date:** 2026-01-04
**Commit:** `c21b463` (phase-6.1/serve-analyze)

## Summary

**Zygote warm start takes 30 SECONDS instead of <1ms** due to IPC protocol mismatch between Rust client and Python Zygote server.

## Root Cause

| Component | Format | Issue |
|:---|:---|:---|
| **Rust IPC** (`ipc.rs`) | `rmp_serde` internally tagged enum | `#[serde(tag = "type")]` produces special MsgPack format |
| **Python Zygote** (`main.py`) | Plain dict | `{"type": "Ready"}` |

**These formats are INCOMPATIBLE.**

### Error Message

```
⚠️ Zygote spawn failed: Socket error: stream did not contain valid UTF-8
   Falling back to normal mode
```

The "UTF-8" error is misleading - it's actually a `rmp_serde` deserialization failure when trying to parse Python's dict format as Rust's internally tagged enum.

## Evidence

**Benchmark Output:**
```
Cold start:   22.3ms
Warm start:   30038.7ms  ← TIMEOUT (30 second fallback)
Speedup: 0.0x           ← SHOULD BE >1x
```

**IPC Logs (Python side works correctly):**
```
[IPC SEND] {'type': 'Ready'}
[IPC RECV] ['Fork', '/tmp/test.py', ...]
[IPC SEND] {'type': 'Forked', 'worker_pid': 92633, 'exit_code': 0}
```

## Technical Analysis

### Python sends:
```python
{"type": "Ready"}  
# MsgPack: 81 a4 74 79 70 65 a5 52 65 61 64 79
```

### Rust expects (serde internally tagged):
```rust
#[serde(tag = "type")]
enum ZygoteResponse { Ready, ... }
// rmp_serde expects different byte format for internally tagged enums
```

## Solution Options

### Option A: Change Rust to externally tagged (Recommended)
Remove `#[serde(tag = "type")]` and use default serde format:
```rust
#[derive(Serialize, Deserialize)]
pub enum ZygoteResponse {
    Ready,
    Forked { worker_pid: u32, exit_code: Option<i32> },
    ...
}
```

Then Python must send: `{"Ready": null}` or `{"Forked": {"worker_pid": 123}}`

### Option B: Use adjacently tagged
```rust
#[serde(tag = "type", content = "data")]
```
Python sends: `{"type": "Ready", "data": null}`

### Option C: Custom deserializer
Implement manual deserialization that accepts Python's dict format.

## Impact

- **Zygote Mode BROKEN** - all warm starts timeout (30s)
- **Performance benefit LOST** - users see 0.0x speedup
- **BLOCKS Phase 6.1 merge**

## Acceptance Criteria

- [ ] `velo run --zygote /path/to/script.py` completes in <100ms
- [ ] Benchmark shows speedup >1x
- [ ] Rust and Python IPC formats compatible
- [ ] All existing Zygote tests pass

## Related

- RFC: OPT-0010-001 MessagePack IPC
- Files: `src/zygote/ipc.rs`, `velo_zygote/main.py`
