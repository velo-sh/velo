# DEF-61-004: Architect Handover Document

> **Author**: Architect (Session 1)
> **Date**: 2026-01-04
> **Status**: Ready for Developer Implementation
> **Branch**: `hotfix/protocol-socket-isolation`

---

## 📋 Executive Summary

DEF-61-004 addresses a **30-second timeout issue** caused by protocol mismatch after Velo binary upgrade (JSON → MessagePack). The solution isolates socket paths by protocol version.

| Metric | Value |
|--------|-------|
| Design Status | ✅ Complete, Expert-Reviewed |
| Implementation Status | ✅ Complete (Phase 1+2) |
| Documentation Status | ✅ Complete |
| QA Test Cases | ✅ 17 tests defined |
| Expert Reviews | 13 (8 Runtime + 4 QA + 1 Protocol Design) |

---

## 🎯 Problem Statement

**Before Fix**:
```
Old Zygote (JSON) ← connects ← New CLI (MessagePack)
                         ↓
              30s timeout (protocol mismatch)
```

**After Fix**:
```
Old socket: /tmp/velo-{uid}/zygote-v00.sock (unused)
New socket: /tmp/velo-{uid}/zygote-v01.sock ← New CLI connects here
                         ↓
              Immediate success (no conflict)
```

---

## 📁 Deliverables Produced

| Document | Path | Purpose |
|----------|------|---------|
| Main Design | `docs/qa/DEFECTS/DEF-61-004-protocol-socket-isolation.md` | Full technical spec |
| QA Review | `docs/qa/DEFECTS/DEF-61-004-qa-review.md` | QA expert findings |
| Dev Checklist | `docs/qa/DEFECTS/DEF-61-004-dev-checklist.md` | Developer task list |
| QA Checklist | `docs/qa/DEFECTS/DEF-61-004-qa-checklist.md` | 17 test cases |
| Magic Handshake | `docs/qa/DEFECTS/DEF-61-004-magic-handshake.md` | v0.7.0 enhancement spec |
| QA Tests | `tests/qa/test_def_61_004_*.py` | Automated tests |

---

## 🔧 Implementation Status

### Rust Side (`src/zygote/ipc.rs`)

| Function | Status | Notes |
|----------|--------|-------|
| `PROTOCOL_VERSION` | ✅ | 0x01, exported |
| `get_socket_dir()` | ✅ | XDG_RUNTIME_DIR → /tmp/velo-{uid} → /tmp fallback |
| `default_socket_path()` | ✅ | `velo-zygote-v{:02x}.sock` |
| `is_socket_alive()` | ✅ | Connection test |
| `cleanup_stale_sockets()` | ✅ | Remove dead sockets |
| `ensure_socket_dir()` | ✅ | 0700 permissions |

### Rust Side (`src/zygote/mod.rs`)

| Change | Status |
|--------|--------|
| Call `cleanup_stale_sockets()` in `ZygoteLauncher::start()` | ✅ |

### Python Side (`velo_zygote/main.py`)

| Function | Status |
|----------|--------|
| `get_socket_dir()` | ✅ |
| `get_versioned_socket_path()` | ✅ |
| `ensure_socket_dir()` | ✅ |

---

## ⚠️ Outstanding Actions from Protocol Design Expert

These are **documentation improvements** for Developer to apply:

### Action 1: Add Side Effect Documentation

**File**: `src/zygote/ipc.rs` - `is_socket_alive()`

```rust
/// Check if a socket is alive (responds to connection attempt)
///
/// **Side Effect**: This creates an actual connection to the socket.
/// If the socket is alive, the server will accept() this probe connection,
/// then immediately see EOF when we disconnect.
///
/// This is acceptable because:
/// - Probe happens during startup before Zygote is running
/// - Used only in `cleanup_stale_sockets()` to detect dead sockets
```

### Action 2: Add Version Coupling Documentation

**File**: `src/zygote/ipc.rs` - `PROTOCOL_VERSION`

```rust
/// Protocol version (ADV-1 + DEF-61-004)
///
/// Used in:
/// - Message framing: [Length 4B LE] [Version 1B] [Payload MsgPack]
/// - Socket path: velo-zygote-v{:02x}.sock
///
/// **Important**: Incrementing this value creates a new socket path.
/// Old processes using the previous socket will not interfere.
pub const PROTOCOL_VERSION: u8 = 0x01;
```

### Action 3: Move PROTOCOL_VERSION to File Top

Currently at line ~207, should be near line ~22 for better code organization.

---

## 🔮 Future Work (v0.7.0)

Documented in `DEF-61-004-magic-handshake.md`:

| Feature | Description |
|---------|-------------|
| Magic Handshake | `b"VELO"` + version byte at connection start |
| PROTOCOL_VERSION | Upgrade to 0x02 |
| Error Messages | Clear "version mismatch" with upgrade hint |

---

## 🧪 Testing Status

| Test Suite | Status |
|------------|--------|
| `cargo test` (182 lib) | ✅ Pass |
| `zygote_basic` (6 tests) | ✅ Pass |
| `zygote_ipc` (5 tests) | ✅ Pass |
| QA Tests (17 defined) | ⏳ Ready for QA |

---

## 📝 For Next Architect Session

### If Continuing DEF-61-004:

1. All design work is complete
2. Implementation is complete
3. Remaining: Developer documentation actions (3 items above)
4. Then: QA runs `test_def_61_004_*.py`

### If Starting New Work:

1. DEF-61-004 is ready for merge after QA approval
2. v0.7.0 Magic Handshake spec is ready for future RFC

---

## 🔗 Key References

| Item | Link |
|------|------|
| Parent RFC | `docs/rfcs/OPT-0010-001-msgpack-ipc.md` |
| Branch | `hotfix/protocol-socket-isolation` |
| Main Spec | `docs/qa/DEFECTS/DEF-61-004-protocol-socket-isolation.md` |
| AGENTS.md | Read first for role governance |

---

**Architect Sign-off**: ✅ Complete
**Handover Date**: 2026-01-04 18:25
