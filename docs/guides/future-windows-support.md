# Phase 6.x Windows Platform Support (Future Work)

> **RFC**: [RFC-0010](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Author**: Windows Platform Expert  
> **Date**: 2026-01-04  
> **Status**: FUTURE WORK (Not Scheduled)

---

## Overview

Windows support is tracked separately due to significant API differences from Unix platforms. This document captures the requirements for when Windows support is prioritized.

---

## 1. File Watching (WIN-P0-001)

### Problem

Windows uses `ReadDirectoryChangesW` API instead of inotify or FSEvents.

### Considerations

- `notify` crate abstracts this, but behavior differs
- Windows has **no recursive watch limit** (unlike inotify's 8192)
- Windows may coalesce events differently than FSEvents

### Implementation

```rust
#[cfg(target_os = "windows")]
fn configure_watcher_windows(watcher: &mut RecommendedWatcher) {
    // Windows-specific: ReadDirectoryChangesW doesn't need special config
    // But may want to adjust buffer size for high-traffic directories
}
```

---

## 2. Path Separator Handling (WIN-P0-002)

### Problem

Windows uses backslash `\`, Unix uses forward slash `/`.

### Critical Locations

- `detect_app.py` module path parsing
- Static Import Graph path storage
- CLI argument parsing

### Implementation

```rust
fn normalize_path(path: &Path) -> String {
    // Always use forward slashes internally (POSIX-style)
    path.to_string_lossy().replace('\\', "/")
}
```

---

## 3. Signal Handling (WIN-P0-003)

### Problem

Windows doesn't have POSIX signals. Uses Console Control Handlers instead.

### Implementation

```rust
#[cfg(target_os = "windows")]
fn setup_ctrl_handler() -> Result<()> {
    use ctrlc;
    
    ctrlc::set_handler(move || {
        // Kill child processes
        // Exit cleanly
    })?;
    Ok(())
}
```

---

## 4. Process Termination (WIN-P0-004)

### Problem

Windows doesn't have `SIGTERM`. Must use `TerminateProcess`.

### Implementation

```rust
#[cfg(target_os = "windows")]
fn kill_child(child: &mut Child) -> Result<()> {
    // TerminateProcess with exit code 1
    child.kill()?;
    Ok(())
}
```

---

## 5. Antivirus Interference (WIN-P1-001)

### Problem

Windows Defender and third-party AV may:
- Lock Python files temporarily
- Delay file system events
- Slow down process spawning

### Recommendation

Document known issues and workaround:
```
If file watching is slow on Windows:
1. Add project directory to antivirus exclusions
2. Disable real-time scanning for development folders
```

---

## 6. UNC Path Support (WIN-P1-002)

### Problem

Network drives use UNC paths (`\\server\share\`).

### Consideration

File watching on network drives may not work reliably.

### Recommendation

Document as unsupported for initial Windows release.

---

## 7. Python Launcher (WIN-P1-003)

### Problem

Windows uses `py.exe` launcher, not direct `python` command.

### Implementation

```rust
#[cfg(target_os = "windows")]
fn detect_python() -> Result<PathBuf> {
    // Try py.exe first (official Windows launcher)
    if let Ok(output) = Command::new("py")
        .arg("-c")
        .arg("import sys; print(sys.executable)")
        .output() 
    {
        // Parse output
    }
    // Fallback to python.exe in PATH
}
```

---

## 8. WSL Compatibility (WIN-P1-004)

### Problem

Users on WSL (Windows Subsystem for Linux) expect Linux behavior.

### Recommendation

Detect WSL and use Linux code path:

```rust
fn is_wsl() -> bool {
    std::fs::read_to_string("/proc/version")
        .map(|s| s.to_lowercase().contains("microsoft"))
        .unwrap_or(false)
}
```

---

## Summary

| ID | Requirement | Priority |
|----|-------------|----------|
| WIN-P0-001 | ReadDirectoryChangesW file watching | P0 |
| WIN-P0-002 | Path separator normalization | P0 |
| WIN-P0-003 | Console Control Handlers (Ctrl+C) | P0 |
| WIN-P0-004 | TerminateProcess for child kill | P0 |
| WIN-P1-001 | Antivirus interference docs | P1 |
| WIN-P1-002 | UNC path support | P1 |
| WIN-P1-003 | py.exe launcher detection | P1 |
| WIN-P1-004 | WSL compatibility detection | P1 |

---

**Status**: Future Work - Not currently scheduled.
