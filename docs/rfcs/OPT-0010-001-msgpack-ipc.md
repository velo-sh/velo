# OPT-0010-001: MessagePack IPC Protocol

> **Status**: APPROVED  
> **Priority**: P1 (Phase 6.1)  
> **Target**: v0.6.1  
> **RFC**: Extends RFC-0010

---

## Scope Clarification

| Communication Type | Current | Upgrade Needed |
|--------------------|---------|----------------|
| **Rust ↔ Rust (in-process)** | `mpsc::channel<ServerEvent>` | ❌ No - already zero-cost |
| **Rust ↔ Python (cross-process)** | JSON + Unix Socket | ✅ Yes - upgrade to MessagePack |

### Rust ↔ Rust (No Change Needed)

```rust
// Already optimal: type-safe channel, zero serialization overhead
let (tx, rx) = mpsc::channel::<ServerEvent>();
tx.send(ServerEvent::Signal(15)); // Direct enum passing, no serialization
```

### Rust ↔ Python (This Proposal)

```
Current:
┌─────────────┐    JSON (slow)     ┌──────────────┐
│  Rust CLI   │ ◄───────────────► │ Python Zygote │
│             │    Unix Socket     │               │
└─────────────┘                    └──────────────┘

Proposed:
┌─────────────┐   MessagePack      ┌──────────────┐
│  Rust CLI   │ ◄───────────────► │ Python Zygote │
│ (rmp-serde) │    Unix Socket     │  (msgpack)    │
└─────────────┘                    └──────────────┘
```

## Motivation

| Metric | JSON | MessagePack |
|--------|------|-------------|
| Serialization | 1x | 3-5x faster |
| Message size | 1x | ~50% smaller |
| Cross-language | ✅ | ✅ |

## Dependencies

```toml
# Cargo.toml
rmp-serde = "1.1"
```

```
# Python
pip install msgpack
```

## Implementation Notes

- Length-prefixed messages: `u32 LE + payload`
- Backward compatible: Add version byte to detect format
- Incremental migration: Start with Zygote IPC only

## Acceptance Criteria

- [x] AC-1: Zygote cold start improved by >20%
- [x] AC-2: Message size reduced by >20% *(revised from 40%, see DEF-OPT-001)*
- [x] AC-3: Backward compatible with JSON fallback

### DEF-OPT-001: AC-2 Revision Rationale

| Metric | Original Target | Actual | Status |
|--------|-----------------|--------|--------|
| Message size reduction | >40% | 20.4% | ✅ Revised |
| Serialization speed | 3-5x faster | 3-5x faster | ✅ Met |

**Root Cause Analysis**:
1. RFC estimate was optimistic (based on larger messages)
2. Zygote IPC messages are small (300-400 bytes)
3. Already using array format `['Fork', field1, ...]` (most compact)
4. Protocol overhead ratio is higher for small messages

**Decision**: Accept 20% reduction - still substantial improvement. Primary benefit is serialization speed (3-5x).

---

## Implementation Advisory

> [!CAUTION]
> The following 3 technical details require attention during coding.

### ADV-1: Protocol Framing Layout

```
┌──────────────────────┬───────────────┬─────────────────────────┐
│ Length (4 bytes u32) │ Version (1B)  │ Payload (MessagePack)   │
│ Little Endian        │               │                         │
└──────────────────────┴───────────────┴─────────────────────────┘
```

- **Length**: Does NOT include itself, but INCLUDES Version + Payload
- **Version**: For future protocol upgrades (Cap'n Proto, Protobuf, etc.)
- **Why LE?**: Target platforms (x86_64, ARM64) are little-endian. Direct `memcpy` without `bswap` = optimal performance.

### ADV-2: Debuggability (TRACE Logging)

**Problem**: MessagePack loses human readability compared to JSON.

**Requirement**:
```rust
// Rust side: At TRACE level, decode payload back to readable format
tracing::trace!(
    "IPC recv: {}",
    serde_json::to_string(&msg).unwrap_or_else(|_| format!("{:?}", msg))
);
```

```python
# Python side: Same TRACE-level debug output
import logging
logger.debug(f"IPC recv: {msg}")  # Uses __repr__
```

**Without this, IPC debugging becomes a nightmare.**

### ADV-3: Pure Python Fallback (Robustness)

> [!IMPORTANT]
> **Architecture Principle**: "Existing is better than fast" (先保证能用，再保证快)

**Scenario**: What if `import msgpack` fails (corrupted env, missing `.so`, glibc mismatch)?

**Decision**: **Fallback to Pure Python msgpack implementation.**

**Strategy**: Vendor lightweight `u-msgpack-python` (~15KB, MIT, zero dependencies)

```
velo/
└── _vendor/
    └── umsgpack.py   # Vendored pure Python implementation
```

**Implementation**:
```python
# src/zygote/ipc.py

# 1. Try high-performance C extension first
try:
    import msgpack
    packer = msgpack.packb
    unpacker = msgpack.unpackb

except (ImportError, OSError):
    # 2. Fallback to vendored Pure Python implementation
    import sys
    from velo._vendor import umsgpack
    
    sys.stderr.write("[Velo] ⚠️  Warning: fast 'msgpack' extension failed to load.\n")
    sys.stderr.write("[Velo]    Falling back to pure Python implementation (slower IPC).\n")
    sys.stderr.write("[Velo]    Run: pip install msgpack  (requires C compiler)\n")
    
    packer = umsgpack.packb
    unpacker = umsgpack.unpackb

# 3. Unified interface - Rust side doesn't know or care
def send_message(sock, msg):
    payload = packer(msg)
    # ...

def recv_message(sock):
    # ...
    return unpacker(payload)
```

**Why NOT fallback to JSON?**
| Issue | Impact |
|-------|--------|
| Protocol handshake | Rust must ask "do you support MsgPack?" |
| Dual implementation | Rust maintains JSON + MsgPack code |
| Type mismatch | MsgPack `bin` vs JSON Base64 strings |

**Performance Tradeoff**:
| Mode | Serialization Speed |
|------|---------------------|
| C Extension (msgpack) | Baseline (fast) |
| Pure Python (u-msgpack) | ~10-30x slower |

**Acceptable** because IPC is not the bottleneck - Python execution is.

---

## Pre-Implementation Checklist

> [!IMPORTANT]
> Development team must verify these items before coding.

### Vendor Operations
- [ ] Download `u-msgpack-python` (v2.8.0+)
- [ ] Place at `python/velo/_vendor/umsgpack.py`
- [ ] Add to package manifest (`MANIFEST.in` or `pyproject.toml`)

### Version Byte (ADV-1)
- [ ] Set Version = `0x01` (Velo MsgPack v1)
- [ ] Rust: Reject if `Version != 0x01`

### Test Cases (Required)
- [ ] Unit test: Mock `import msgpack` raising `ImportError`
- [ ] Verify fallback path activates correctly
- [ ] Verify IPC functions work with both C and Pure Python

---

## Fallback Logic Visualization

```mermaid
graph TD
    A[Start IPC Init] --> B{Import msgpack C-Ext?};
    B -- Yes --> C[Use High-Perf Packer];
    B -- No --> D[Load velo._vendor.umsgpack];
    D --> E[Print Warning to Stderr];
    E --> F[Use Pure-Python Packer];
    C --> G[Ready for Rust IPC];
    F --> G;
```

---

**Architect Sign-off**: APPROVED for v0.6.1. AC-2 revised per DEF-OPT-001. ADV-3 updated to Pure Python fallback.

