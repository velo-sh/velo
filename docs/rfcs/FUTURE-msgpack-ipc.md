# Future Optimization: MessagePack IPC Protocol

> **Status**: PROPOSED  
> **Priority**: P2 (Future)  
> **Target**: v0.7.0+  
> **RFC**: Extends RFC-0010

---

## Summary

Upgrade Rust ↔ Python IPC from JSON to MessagePack for improved performance.

## Motivation

| Metric | JSON | MessagePack |
|--------|------|-------------|
| Serialization | 1x | 3-5x faster |
| Message size | 1x | ~50% smaller |
| Cross-language | ✅ | ✅ |

## Proposed Architecture

```
┌─────────────┐     MessagePack      ┌──────────────┐
│  Rust CLI   │ ◄──────────────────► │ Python Zygote │
│  (rmp-serde)│   Unix Socket        │  (msgpack)    │
└─────────────┘                      └──────────────┘
```

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
