# Future Optimization: MessagePack IPC Protocol

> **Status**: PROPOSED  
> **Priority**: P2 (Future)  
> **Target**: v0.7.0+  
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

- [ ] Zygote cold start improved by >20%
- [ ] Message size reduced by >40%
- [ ] Backward compatible with JSON fallback

---

**Architect Sign-off**: Design approved. Deferred to v0.7.0.
