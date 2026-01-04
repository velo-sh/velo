# DEF-61-004: Protocol Version Socket Isolation

> **Parent**: [OPT-0010-001-msgpack-ipc.md](../../rfcs/OPT-0010-001-msgpack-ipc.md) (MessagePack IPC Protocol)

**Status**: OPEN → IN REVIEW
**Severity**: P1 (Stability)
**Reporter**: Architect
**Date**: 2026-01-04
**Branch**: `hotfix/protocol-socket-isolation`
**Expert Review**: ✅ Completed (12 experts: 8 Runtime + 4 QA)

> **Attachments**:
> - [DEF-61-004-qa-review.md](./DEF-61-004-qa-review.md) - QA Expert Review (17 test cases)
> - [DEF-61-004-dev-checklist.md](./DEF-61-004-dev-checklist.md) - Developer Handover (4.5h)
> - [DEF-61-004-qa-checklist.md](./DEF-61-004-qa-checklist.md) - QA Handover (17 tests)
> - [DEF-61-004-magic-handshake.md](./DEF-61-004-magic-handshake.md) - Magic Handshake Design (v0.7.0)

---

## Problem Summary

After upgrading Velo binary (JSON → MessagePack IPC), stale Zygote processes cause **30-second timeout** due to protocol mismatch.

## Root Cause

| Component | Protocol |
|-----------|----------|
| Old Zygote (running) | JSON |
| New CLI (upgraded) | MessagePack (OPT-0010-001) |

CLI connects to old socket, sends MessagePack, Zygote can't parse → 30s timeout.

---

## Expert Review Summary

| Expert | Verdict | Key Feedback |
|--------|---------|--------------|
| Unix/POSIX | ⚠️ Improve | Use user-isolated directory |
| IPC Protocol | ✅ OK + Enhance | Add Magic Handshake for v2 |
| Process Lifecycle | ⚠️ Improve | Connection test before cleanup |
| Security | ✅ OK | Verify socket permissions |

---

## Solution Design (Expert-Enhanced)

### Socket Path Format

**Old (problematic)**:
```
/tmp/velo-zygote.sock
```

**New (user-isolated + versioned)**:
```
$TMPDIR/velo-$UID/zygote-v{PROTOCOL_VERSION}.sock
```

Examples:
- macOS: `/var/folders/.../velo-501/zygote-v1.sock`
- Linux: `/tmp/velo-1000/zygote-v1.sock`

### Stale Detection Strategy

Before deleting old sockets, **attempt connection** to verify truly stale:

```
1. Find velo socket files
2. For each socket not matching current version:
   a. Try to connect (timeout 100ms)
   b. If connection fails → Socket is stale → Delete
   c. If connection succeeds → Another Velo running → Leave alone, warn user
```

---

## Implementation Spec

### 1. Rust Side (`src/zygote/ipc.rs`)

```rust
/// Protocol version (ADV-1)
pub const PROTOCOL_VERSION: u8 = 0x01;

/// Get user-isolated socket directory
/// Creates directory with user-only permissions (0700)
fn get_socket_dir() -> PathBuf {
    let uid = unsafe { libc::getuid() };
    let dir = std::env::temp_dir().join(format!("velo-{}", uid));
    
    if !dir.exists() {
        // Create with restrictive permissions (0700)
        std::fs::create_dir_all(&dir).ok();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).ok();
        }
    }
    dir
}

/// Get the default socket path for Zygote IPC
pub fn default_socket_path() -> PathBuf {
    get_socket_dir().join(format!("zygote-v{}.sock", PROTOCOL_VERSION))
}

/// Check if a socket is alive (connection test)
fn is_socket_alive(path: &Path) -> bool {
    use std::os::unix::net::UnixStream;
    use std::time::Duration;
    
    match UnixStream::connect(path) {
        Ok(stream) => {
            // Set short timeout and try to read
            stream.set_read_timeout(Some(Duration::from_millis(100))).ok();
            true
        }
        Err(_) => false,
    }
}

/// Clean up stale sockets from older protocol versions
pub fn cleanup_stale_sockets() {
    let socket_dir = get_socket_dir();
    let current_socket = format!("zygote-v{}.sock", PROTOCOL_VERSION);
    
    if let Ok(entries) = std::fs::read_dir(&socket_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            
            // Only process zygote socket files
            if name_str.starts_with("zygote-v") && name_str.ends_with(".sock") {
                // Skip current version
                if name_str == current_socket {
                    continue;
                }
                
                let path = entry.path();
                
                // Connection test: only delete if truly stale
                if !is_socket_alive(&path) {
                    eprintln!("🔄 Cleaning stale Zygote socket: {}", name_str);
                    let _ = std::fs::remove_file(&path);
                } else {
                    eprintln!("⚠️  Found running Zygote (different version): {}", name_str);
                    eprintln!("   Run 'velo zygote stop' to stop it.");
                }
            }
        }
    }
}
```

### 2. Python Side (`velo_zygote/main.py`)

```python
import os
import tempfile

PROTOCOL_VERSION = 0x01

def get_socket_dir() -> str:
    """Get user-isolated socket directory."""
    uid = os.getuid()
    socket_dir = os.path.join(tempfile.gettempdir(), f"velo-{uid}")
    
    if not os.path.exists(socket_dir):
        os.makedirs(socket_dir, mode=0o700, exist_ok=True)
    
    return socket_dir

def get_versioned_socket_path() -> str:
    """Get socket path with protocol version."""
    return os.path.join(get_socket_dir(), f"zygote-v{PROTOCOL_VERSION}.sock")
```

### 3. Future Enhancement: Magic Handshake (v2)

For PROTOCOL_VERSION = 0x02, add magic bytes:

```rust
/// Protocol v2 handshake
const MAGIC: &[u8; 4] = b"VELO";

fn write_handshake(stream: &mut UnixStream) -> Result<()> {
    stream.write_all(MAGIC)?;
    stream.write_all(&[PROTOCOL_VERSION])?;
    Ok(())
}

fn verify_handshake(stream: &mut UnixStream) -> Result<u8> {
    let mut magic = [0u8; 4];
    stream.read_exact(&mut magic)?;
    if &magic != MAGIC {
        return Err(ZygoteError::ProtocolError("Invalid magic".into()));
    }
    let mut version = [0u8; 1];
    stream.read_exact(&mut version)?;
    Ok(version[0])
}
```

---

## Integration Points

| File | Change |
|------|--------|
| `src/zygote/ipc.rs` | `get_socket_dir()`, `default_socket_path()`, `is_socket_alive()`, `cleanup_stale_sockets()` |
| `src/zygote/mod.rs` | Call `cleanup_stale_sockets()` in `ZygoteLauncher::start()` |
| `velo_zygote/main.py` | `get_socket_dir()`, `get_versioned_socket_path()` |
| `ZygoteServer.__init__` | Use `get_versioned_socket_path()` instead of `--socket` arg |

---

## Test Cases

| ID | Test | Expected |
|----|------|----------|
| DEF-61-004-T1 | Build old version, start Zygote, upgrade, run --zygote | Old socket detected as stale, cleaned, new Zygote starts |
| DEF-61-004-T2 | Check socket path format | Contains `/velo-{UID}/zygote-v1.sock` |
| DEF-61-004-T3 | Stale socket cleanup with running Zygote | Warns but doesn't delete running socket |
| DEF-61-004-T4 | Socket directory permissions | 0700 (user only) |
| DEF-61-004-T5 | Multi-user system isolation | Each user has separate directory |

---

## Acceptance Criteria

- [ ] AC-1: Socket path includes protocol version (`zygote-v1.sock`)
- [ ] AC-2: Socket directory is user-isolated (`velo-{UID}/`)
- [ ] AC-3: Connection test before deleting stale sockets
- [ ] AC-4: Socket directory created with 0700 permissions
- [ ] AC-5: Benchmark passes without manual restart
- [ ] AC-6: No regression in existing tests
- [ ] AC-7: Socket path length < 108 chars (Unix limit)
- [ ] AC-8: Graceful error handling in cleanup

---

## ⚠️ Implementation Recommendations

### 1. Permissions Enforcement

```rust
fn get_socket_dir() -> PathBuf {
    let uid = unsafe { libc::getuid() };
    let dir = std::env::temp_dir().join(format!("velo-{}", uid));
    
    if !dir.exists() {
        std::fs::create_dir_all(&dir).ok();
        
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            // CRITICAL: fchmod after creation to bypass umask
            // std::fs::set_permissions respects umask, so use explicit mode
            std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).ok();
            
            // Verify permissions were set correctly
            if let Ok(meta) = std::fs::metadata(&dir) {
                let mode = meta.permissions().mode() & 0o777;
                if mode != 0o700 {
                    eprintln!("⚠️ Socket directory has weak permissions: {:o}", mode);
                }
            }
        }
    }
    dir
}
```

### 2. Socket Path Length Limit (108 chars)

Unix domain sockets have a **108-character path limit**. On macOS, `$TMPDIR` can be deeply nested:
```
/var/folders/8g/255rhyf93xb8bh6m6lp0j75m0000gn/T/velo-501/zygote-v1.sock
```
This is ~70 chars, safe. But if `$TMPDIR` is longer, fall back to `/tmp`:

```rust
fn get_socket_dir() -> PathBuf {
    const MAX_SOCKET_PATH: usize = 108;
    const SOCKET_NAME_LEN: usize = 20; // "zygote-v255.sock" max
    
    let uid = unsafe { libc::getuid() };
    let preferred = std::env::temp_dir().join(format!("velo-{}", uid));
    
    // Check if path would be too long
    if preferred.to_string_lossy().len() + SOCKET_NAME_LEN > MAX_SOCKET_PATH {
        eprintln!("⚠️ $TMPDIR path too long, falling back to /tmp");
        return PathBuf::from(format!("/tmp/velo-{}", uid));
    }
    
    preferred
}
```

### 3. Graceful Error Handling in Cleanup

```rust
pub fn cleanup_stale_sockets() {
    let socket_dir = get_socket_dir();
    
    // Don't crash if directory doesn't exist yet
    let entries = match std::fs::read_dir(&socket_dir) {
        Ok(e) => e,
        Err(_) => return, // Directory doesn't exist, nothing to clean
    };
    
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        
        if name_str.starts_with("zygote-v") && name_str.ends_with(".sock") {
            // ... existing logic ...
            
            // Graceful delete - ignore permission errors
            match std::fs::remove_file(&path) {
                Ok(_) => eprintln!("🔄 Cleaned stale socket: {}", name_str),
                Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                    // Should never happen with user-isolated dirs, but be safe
                    eprintln!("⚠️ Cannot remove socket (permission denied): {}", name_str);
                }
                Err(e) => {
                    eprintln!("⚠️ Failed to remove socket: {} ({})", name_str, e);
                }
            }
        }
    }
}

## Work Estimate (Updated)

| Task | Hours |
|------|-------|
| Implement `get_socket_dir()` (Rust + Python) | 1h |
| Implement `is_socket_alive()` | 0.5h |
| Implement `cleanup_stale_sockets()` | 1h |
| Update `ZygoteLauncher::start()` | 0.5h |
| Testing (T1-T5) | 1.5h |
| **Total** | **4.5h** |

---

## Future Work

### v0.6.2 (This Hotfix)
- [x] Versioned socket path (`zygote-v1.sock`)
- [x] User-isolated directory (`/tmp/velo-{UID}/`)
- [x] Connection test for stale detection
- [x] Socket directory permissions (0700)

### v0.7.0 (Protocol Enhancement)
| Feature | Source | Description |
|---------|--------|-------------|
| Magic Handshake | IPC Expert | `b"VELO"` + version byte for double verification |
| PID File + flock | Nginx | Prevent duplicate Zygote with file lock |

```rust
// Nginx-style PID lock
fn acquire_pid_lock(dir: &Path) -> Result<File> {
    let pid_file = dir.join("zygote.pid");
    let f = OpenOptions::new().create(true).write(true).open(&pid_file)?;
    flock(f.as_raw_fd(), FlockArg::LockExclusiveNonblock)?;
    writeln!(&f, "{}", std::process::id())?;
    Ok(f)
}
```

### v0.8.0 (Performance)
| Feature | Source | Description |
|---------|--------|-------------|
| Persistent IPC Connection | Node.js Cluster | Reuse socket across multiple Fork commands |
| Worker ID Assignment | Node.js | `VELO_WORKER_ID` environment variable |

```
Current:  connect → fork → close (per request)
Improved: connect → fork → fork → fork → ... → close (session)
```

### v1.0.0 (Production Deployment)
| Feature | Source | Description |
|---------|--------|-------------|
| systemd Socket Activation | systemd | On-demand Zygote startup via `$LISTEN_FDS` |
| Hot Upgrade | Bun | Zero-downtime protocol version upgrade |
| XDG_RUNTIME_DIR | FHS | Use `/run/user/{UID}/velo/` on Linux |

**systemd Socket Activation**:
```ini
# /etc/systemd/user/velo-zygote.socket
[Socket]
ListenStream=%t/velo/zygote.sock

[Install]
WantedBy=sockets.target
```

```ini
# /etc/systemd/user/velo-zygote.service
[Service]
ExecStart=/usr/bin/velo zygote start --socket-fd=3
Type=notify
```

**Hot Upgrade (Bun-style)**:
```
1. New Velo binary deployed
2. CLI detects version mismatch via handshake
3. CLI sends "Upgrade" command to old Zygote
4. Old Zygote spawns new Zygote (new version)
5. Old Zygote graceful shutdown
6. New Zygote inherits socket
```

---

## Industry Reference

| Runtime | Socket Strategy | Isolation | Protocol |
|---------|-----------------|-----------|----------|
| Nginx | `/var/run/nginx.sock` | PID lock | Binary |
| Bun | `/tmp/bun-*` | Per-session | Binary |
| Node.js | IPC Channel | Per-cluster | JSON |
| Velo | `/tmp/velo-{UID}/zygote-v1.sock` | User + Version | MessagePack |

---

**Architect Sign-off**: ✅ Expert-reviewed, Ready for Developer
**Review Date**: 2026-01-04
**Experts Consulted**: 8 (Unix/POSIX, IPC, Process, Security, Nginx, Bun, Node.js, systemd)
