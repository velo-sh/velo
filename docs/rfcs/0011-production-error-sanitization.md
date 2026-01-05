# RFC-0011: Production Mode Error Sanitization

**Status**: 📋 PROPOSED (Future Work)
**Phase**: TBD
**Priority**: P3 (Enhancement)
**Author**: QA Working Group
**Date**: 2026-01-05

---

## 1. Problem Statement

Currently, Velo displays full absolute paths in error messages (e.g., `/home/runner/work/velo/velo/foo.py`). While this is acceptable for development, it represents a minor information disclosure in production environments.

### Current Behavior
```
ModuleNotFoundError: No module named 'foo'
  File "/home/user/myproject/app.py", line 1
```

### Desired Production Behavior
```
Error: Application failed to start (E001)
See logs for details.
```

## 2. Industry Analysis

| Project | Production Error Handling |
| :--- | :--- |
| **Node.js** | Disable verbose errors via `NODE_ENV=production` |
| **Django** | `DEBUG=False` hides all detailed errors |
| **CPython** | Displays full paths (standard behavior) |
| **Go** | Configurable via logging packages |

**Consensus**: Environment-aware error output, not path replacement.

## 3. Proposed Solution

### Option A: Environment-Aware Error Output (Recommended)
```rust
fn format_error(err: &ServeError, mode: ErrorMode) -> String {
    match mode {
        ErrorMode::Development => {
            // Full path, stack trace, hints
            format!("{}\n  --> {}", err.message, err.source_path)
        }
        ErrorMode::Production => {
            // Minimal, code-only
            format!("Error: {} (code: {})", err.summary, err.code)
        }
    }
}
```

### Activation
```bash
# Via environment
VELO_ENV=production velo serve main:app

# Via CLI flag  
velo serve main:app --production
```

## 4. Alternatives Considered

| Option | Description | Verdict |
| :--- | :--- | :--- |
| B. Path Relativization | Replace `/home/user/` with `./` | Partial protection only |
| C. Path Stripping | Remove all paths | Breaks debugging |
| A. Environment Mode | ✅ Industry standard | **Recommended** |

## 5. Test Cases (Deferred)

- `test_production_mode_no_path_disclosure`: Verify no paths in `--production` output
- `test_development_mode_full_paths`: Verify full paths in default mode
- `test_log_file_full_paths`: Verify logs always contain full paths regardless of mode

## 6. References

- OWASP: Full Path Disclosure (FPD) vulnerability
- Node.js Security Best Practices
- Django Security Settings

---

## Status Tracking

- [ ] RFC Approved
- [ ] Implementation Started
- [ ] Tests Added
- [ ] Documentation Updated
