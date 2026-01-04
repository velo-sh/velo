# DEF-61-004: Magic Handshake Design (v0.7.0)

> **Parent**: [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md)
> **Type**: Future Enhancement Specification
> **Target Version**: v0.7.0
> **Priority**: P2 (Defense in Depth)

---

## 🎯 Purpose

**双重保险**: 防止误连接到非 Velo 的 Unix Socket,提供快速协议版本检测。

| 场景 | 仅版本号隔离 (v0.6.2) | Magic + 版本号 (v0.7.0) |
|------|----------------------|------------------------|
| 连接到其他程序 Socket | ❌ 可能误判 | ✅ 100ms 内拒绝 |
| 协议版本不匹配 | ⚠️ 30s 超时 | ✅ 立即检测 |
| 调试诊断 | 模糊错误 | 清晰错误信息 |
| 误操作恢复 | 需等待 | 立即失败 |

---

## 🔄 Connection Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Magic Handshake 流程                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   CLI (Rust)                       Zygote (Python)          │
│    │                                 │                      │
│    │──── connect(socket) ───────────►│                      │
│    │                                 │                      │
│    │◄──── "VELO" + 0x02 ────────────│  Step 1: Zygote 先发  │
│    │                                 │                      │
│    │     Step 2: CLI 验证            │                      │
│    │     ├── Magic = "VELO"?         │                      │
│    │     └── Version compatible?     │                      │
│    │                                 │                      │
│    │     ❌ 不匹配:                  │                      │
│    │        disconnect()             │                      │
│    │        print("Protocol error")  │                      │
│    │                                 │                      │
│    │     ✅ 匹配:                    │                      │
│    │        continue protocol        │                      │
│    │                                 │                      │
│    │──── Fork Command ──────────────►│  Step 3: 正常通信    │
│    │◄──── Forked Response ──────────│                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Wire Format

### Handshake Phase (Connection Establishment)

```
┌────────────────────────────────────────┐
│           Handshake Message            │
├──────────────┬─────────────────────────┤
│ Offset 0-3   │ Magic: "VELO" (ASCII)   │
│              │ 0x56 0x45 0x4C 0x4F     │
├──────────────┼─────────────────────────┤
│ Offset 4     │ Protocol Version        │
│              │ 0x02 (for v0.7.0)       │
├──────────────┼─────────────────────────┤
│ Offset 5-8   │ Zygote PID (optional)   │
│              │ u32 LE                  │
└──────────────┴─────────────────────────┘
Total: 5 bytes (or 9 bytes with PID)
```

### Message Phase (After Handshake)

```
┌──────────────┬──────────────┬────────────────┐
│ Length       │ Version      │ MessagePack    │
│ 4 bytes LE   │ 1 byte       │ N bytes        │
│ u32          │ 0x02         │ Payload        │
└──────────────┴──────────────┴────────────────┘
```

---

## 🧠 Design Rationale

### Why "VELO" (4 bytes)?

```rust
const MAGIC: &[u8; 4] = b"VELO";
```

| Design Choice | Rationale |
|--------------|-----------|
| **4 bytes** | Standard magic number size, sufficient uniqueness |
| **ASCII readable** | Easy to debug with hexdump |
| **Program identifier** | Immediately identifies Velo protocol |

**Industry Comparison**:
| Program | Magic Bytes |
|---------|-------------|
| Git Pack | `PACK` |
| PNG | `\x89PNG` |
| PDF | `%PDF` |
| ELF | `\x7fELF` |
| **Velo** | `VELO` |

### Why Zygote Sends First?

```
Zygote (Server) ──sends──> "VELO" + version ──to──> CLI (Client)
```

| Approach | Pros | Cons |
|----------|------|------|
| **Server First** ✅ | Client can detect wrong connection immediately | - |
| Client First | - | Server may block waiting for data |

**Reasoning**: The client initiated the connection, so it's waiting for a response. Server-first handshake allows the client to validate immediately without deadlock risk.

### Version Negotiation Capability

```rust
fn verify_handshake(stream: &mut UnixStream) -> Result<u8> {
    // Read and verify magic
    let mut magic = [0u8; 4];
    stream.read_exact(&mut magic)?;
    if &magic != MAGIC {
        return Err(ZygoteError::ProtocolError("Invalid magic".into()));
    }
    
    // Read and return version for negotiation
    let mut version = [0u8; 1];
    stream.read_exact(&mut version)?;
    Ok(version[0])  // Caller can decide compatibility
}
```

**Future Extension**:
```rust
let remote_version = verify_handshake(&mut stream)?;

match remote_version.cmp(&PROTOCOL_VERSION) {
    Ordering::Equal => { /* Perfect match */ }
    Ordering::Greater => {
        warn!("Server is newer (v{}), some features may not work", remote_version);
    }
    Ordering::Less => {
        warn!("Server is older (v{}), falling back to compatibility mode", remote_version);
    }
}
```

---

## 💻 Implementation Spec

### Rust Side (`src/zygote/ipc.rs`)

```rust
/// Magic bytes for protocol identification
const MAGIC: &[u8; 4] = b"VELO";

/// Protocol version for v0.7.0
pub const PROTOCOL_VERSION: u8 = 0x02;

/// Send handshake (called by Zygote after accept)
pub fn send_handshake(stream: &mut UnixStream) -> Result<()> {
    stream.write_all(MAGIC)?;
    stream.write_all(&[PROTOCOL_VERSION])?;
    stream.flush()?;
    Ok(())
}

/// Verify handshake (called by CLI after connect)
pub fn verify_handshake(stream: &mut UnixStream) -> Result<u8> {
    // Set short timeout for handshake
    stream.set_read_timeout(Some(Duration::from_millis(500)))?;
    
    // Read magic
    let mut magic = [0u8; 4];
    stream.read_exact(&mut magic)?;
    
    if &magic != MAGIC {
        return Err(ZygoteError::ProtocolError(format!(
            "Invalid magic: expected 'VELO', got {:?}",
            std::str::from_utf8(&magic).unwrap_or("<binary>")
        )));
    }
    
    // Read version
    let mut version = [0u8; 1];
    stream.read_exact(&mut version)?;
    
    // Restore normal timeout
    stream.set_read_timeout(Some(Duration::from_secs(30)))?;
    
    Ok(version[0])
}

/// Check version compatibility
pub fn check_version_compatibility(remote_version: u8) -> Result<()> {
    if remote_version != PROTOCOL_VERSION {
        return Err(ZygoteError::ProtocolError(format!(
            "Protocol version mismatch: CLI is v{}, Zygote is v{}. \
             Please restart Zygote: velo zygote stop && velo zygote start",
            PROTOCOL_VERSION, remote_version
        )));
    }
    Ok(())
}
```

### Python Side (`velo_zygote/main.py`)

```python
import struct

MAGIC = b"VELO"
PROTOCOL_VERSION = 0x02

def send_handshake(conn: socket.socket) -> None:
    """Send handshake after accepting connection."""
    conn.sendall(MAGIC + bytes([PROTOCOL_VERSION]))

def receive_handshake(conn: socket.socket) -> int:
    """Receive and verify handshake (if client sends one in future)."""
    data = conn.recv(5)
    if len(data) < 5:
        raise ProtocolError("Handshake incomplete")
    
    magic = data[:4]
    version = data[4]
    
    if magic != MAGIC:
        raise ProtocolError(f"Invalid magic: {magic!r}")
    
    return version
```

---

## 🔀 Migration Path

### v0.6.2 → v0.7.0 Upgrade

```
Phase 1: Add handshake to Zygote (server side)
         - Zygote sends "VELO" + 0x02 after accept
         - Old CLI ignores initial bytes (protocol still works)

Phase 2: Add handshake verification to CLI
         - CLI checks for "VELO" magic
         - CLI verifies version compatibility
         - Clear error message if mismatch

Phase 3: Require handshake
         - Reject connections without valid handshake
         - This is when v0.6.x CLI stops working
```

### Backward Compatibility Window

| CLI Version | Zygote v0.6.2 | Zygote v0.7.0 |
|-------------|---------------|---------------|
| v0.6.2 | ✅ Works | ⚠️ Works (ignores handshake) |
| v0.7.0 | ❌ Fails (no handshake) | ✅ Works |

---

## 🧪 Test Cases

| ID | Test | Expected |
|----|------|----------|
| HS-001 | Connect to Velo Zygote | Magic "VELO" + version received |
| HS-002 | Connect to non-Velo socket | Error within 500ms |
| HS-003 | Version mismatch | Clear error with upgrade hint |
| HS-004 | Partial handshake (timeout) | Error within 500ms |
| HS-005 | Corrupted magic bytes | Error with hex dump |

---

## 📈 Performance Impact

| Operation | Before | After | Delta |
|-----------|--------|-------|-------|
| Connection setup | ~2ms | ~3ms | +1ms |
| Error detection | 30s | 0.5s | **-29.5s** |

**Net benefit**: Faster failure is better than slow timeout.

---

## 🔗 References

- [DEF-61-004-protocol-socket-isolation.md](./DEF-61-004-protocol-socket-isolation.md) - Parent design
- [OPT-0010-001-msgpack-ipc.md](../../rfcs/OPT-0010-001-msgpack-ipc.md) - IPC Protocol RFC

---

**Author**: Architect
**Date**: 2026-01-04
**Status**: 📅 Planned for v0.7.0
