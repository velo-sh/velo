# DEF-61-004: Protocol Version Socket Isolation

**Status**: OPEN
**Severity**: P1 (Stability)
**Reporter**: Architect
**Date**: 2026-01-04
**Branch**: `hotfix/protocol-socket-isolation`

---

## Problem Summary

After upgrading Velo binary (JSON → MessagePack IPC), stale Zygote processes cause **30-second timeout** due to protocol mismatch.

## Root Cause

| Component | Protocol |
|-----------|----------|
| Old Zygote (running) | JSON |
| New CLI (upgraded) | MessagePack (OPT-0010-001) |

CLI connects to old socket, sends MessagePack, Zygote can't parse → 30s timeout.

## Reproduction

```bash
# 1. Run old Velo (JSON protocol)
./target/release/velo zygote start

# 2. Upgrade Velo (cargo build --release with MessagePack)

# 3. Run with --zygote
./target/release/velo run --zygote script.py
# → 30 second timeout!
```

---

## Solution Design

### Approach: Socket Path with Protocol Version

**Current**:
```
/tmp/velo-zygote.sock
```

**Proposed**:
```
/tmp/velo-zygote-v{PROTOCOL_VERSION}.sock
```

Example: `/tmp/velo-zygote-v1.sock`

---

## Implementation Spec

### 1. Rust Side (`src/zygote/ipc.rs`)

```rust
/// Protocol version (ADV-1)
pub const PROTOCOL_VERSION: u8 = 0x01;

/// Get the default socket path for Zygote IPC
/// Socket path now includes protocol version for isolation
pub fn default_socket_path() -> PathBuf {
    std::env::temp_dir().join(format!("velo-zygote-v{}.sock", PROTOCOL_VERSION))
}

/// Clean up stale sockets from older protocol versions
pub fn cleanup_stale_sockets() {
    let temp = std::env::temp_dir();
    let current_socket = format!("velo-zygote-v{}.sock", PROTOCOL_VERSION);
    
    // Find and remove old version sockets
    if let Ok(entries) = std::fs::read_dir(&temp) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            
            if name_str.starts_with("velo-zygote-v") 
               && name_str.ends_with(".sock")
               && name_str != current_socket 
            {
                eprintln!("🔄 Cleaning stale Zygote socket: {}", name_str);
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }
}
```

### 2. Python Side (`velo_zygote/main.py`)

```python
PROTOCOL_VERSION = 0x01

# In ZygoteServer.__init__ or at module level
def get_versioned_socket_path():
    import tempfile
    return f"{tempfile.gettempdir()}/velo-zygote-v{PROTOCOL_VERSION}.sock"
```

### 3. Integration Points

| File | Change |
|------|--------|
| `src/zygote/ipc.rs` | `default_socket_path()` includes version |
| `src/zygote/mod.rs` | Call `cleanup_stale_sockets()` on start |
| `velo_zygote/main.py` | Match socket naming pattern |

---

## Test Cases

| ID | Test | Expected |
|----|------|----------|
| DEF-61-004-T1 | Build old version, start Zygote, build new version, run --zygote | No timeout, new Zygote starts |
| DEF-61-004-T2 | Check socket path format | Contains `-v1` suffix |
| DEF-61-004-T3 | Stale socket cleanup | Old sockets removed on start |

---

## Acceptance Criteria

- [ ] AC-1: Socket path includes protocol version
- [ ] AC-2: Old sockets cleaned on Zygote start
- [ ] AC-3: Benchmark passes without manual restart
- [ ] AC-4: No regression in existing tests

---

## Work Estimate

| Task | Hours |
|------|-------|
| Implement Rust changes | 0.5h |
| Implement Python changes | 0.5h |
| Add cleanup logic | 1h |
| Testing | 1h |
| **Total** | **3h** |

---

**Architect Sign-off**: Ready for Developer
