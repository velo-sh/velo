# RFC-0022: Operational Experience Standards (Security & Performance UX)

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-12
**Priority**: P1 (Critical Experience Standards)

## 1. Problem Statement

Current Velo security restrictions are **silent**:
- Environment variables filtered without warning
- Import paths blocked without feedback
- Users have no visibility into what's happening

This leads to:
1. **Frustration**: "Why doesn't my app work?"
2. **Debugging difficulty**: No hints about security filtering
3. **False bug reports**: Users think Velo is broken

## 2. Proposed Solution

### 2.1 Dev-Mode (`VELO_ENV=dev`)

A relaxed security mode for local development:

| Setting | Production | Dev-Mode |
|:---|:---|:---|
| Environment filtering | Strict whitelist | Expanded whitelist |
| Import path restrictions | Minimal | Relaxed |
| Security warnings | Errors | Warnings only |
| Startup feedback | Silent | Verbose |

### 2.2 Startup Security Banner

On startup, Velo MUST display security status:

```
╔════════════════════════════════════════════════════════════════╗
║  VELO Security Mode: DEVELOPMENT                              ║
║  ──────────────────────────────────────────────────────────────║
║  ⚠️  DEV MODE: Relaxed security for local development         ║
║  • Environment: 42 variables allowed (5 filtered)             ║
║  • Import paths: 12 trusted prefixes                           ║
║  • Set VELO_ENV=prod for production hardening                 ║
╚════════════════════════════════════════════════════════════════╝
```

### 2.3 Filtered Variable Logging

When variables are filtered, log at DEBUG level:

```
[VELO:DEBUG] Security filter: Removed environment variable 'LD_PRELOAD'
[VELO:DEBUG] Security filter: Removed environment variable 'DYLD_LIBRARY_PATH'
[VELO:INFO]  2 environment variables filtered (use VELO_LOG=debug for details)
```

### 2.4 First-Run Guidance

On first run or when filter triggers, provide actionable guidance:

```
[VELO:WARN] Your application may be affected by security restrictions.
            To relax restrictions for development:
              export VELO_ENV=dev
            To add a custom variable to whitelist:
              Add to pyproject.toml: [tool.velo.security] env_whitelist = ["MY_VAR"]
```

## 3. Implementation Requirements

### 3.1 Config Changes

```toml
# config/constants.toml (NEW)
[security.modes]
dev = { strict = false, log_filtered = true }
ci = { strict = true, log_filtered = true }
prod = { strict = true, log_filtered = false }
```

### 3.2 Code Changes

| File | Change |
|:---|:---|
| `src/lifecycle/safety.rs` | Add logging to `EnvironmentShield::apply()` |
| `src/cmd/run.rs` | Add startup security banner |
| `src/config.rs` | Add `VeloSecurityMode` enum |
| `velo_zygote/launcher.py` | Python-side banner and logging |

### 3.3 Environment Detection

```rust
enum VeloSecurityMode {
    Dev,   // VELO_ENV=dev or VELO_ENV not set + not CI
    CI,    // CI=true or GITHUB_ACTIONS=true
    Prod,  // VELO_ENV=prod
}
```

## 4. Quality Gates

- **Gate Q (UX-001)**: Startup MUST display security mode banner
- **Gate R (UX-002)**: Filtered variables MUST be logged (DEBUG level minimum)
- **Gate S (UX-003)**: First filter event MUST trigger guidance message

## 5. Verification Plan

### 5.1 Unit Tests

| Test | Description |
|:---|:---|
| `test_security_banner_dev_mode` | Verify banner shows in dev mode |
| `test_security_banner_prod_mode` | Verify banner shows in prod mode |
| `test_filtered_variable_logging` | Verify filtered vars are logged |

### 5.2 Manual Verification

1. Run `VELO_ENV=dev velo run main:app` - should see DEV banner
2. Run `VELO_ENV=prod velo run main:app` - should see PROD banner
3. Set `MY_DANGEROUS_VAR=x`, run Velo, check logs for filter message

## 6. Phase Assignment

| Feature | Phase | Priority |
|:---|:---|:---|
| Startup security banner | 7.2 | ⭐⭐⭐ P1 |
| Filtered variable logging | 7.2 | ⭐⭐⭐ P1 |
| Searchable error codes | 7.2 | ⭐⭐⭐ P1 |
| Auto-detect dev-mode | 7.2 | ⭐⭐ P2 |
| pyproject.toml integration | 7.2 | ⭐⭐ P2 |
| Dev-mode relaxed restrictions | 7.2 | ⭐⭐ P2 |
| `velo security check` command | 8.x | ⭐ P3 |
| First-run guidance | 8.x | ⭐ P3 |
| Failure diagnostics | 8.x | ⭐ P3 |

---

## 7. Best Practices (Industry Standards)

### 7.1 Searchable Error Codes

All security-related messages MUST use unique, searchable error codes:

| Code | Category | Example |
|:---|:---|:---|
| `VELO-SEC-001` | Env Filtered | `Environment variable 'MY_VAR' was filtered` |
| `VELO-SEC-002` | Path Blocked | `Import path '/suspicious' was blocked` |
| `VELO-SEC-003` | FD Hygiene | `File descriptor 5 was closed` |

**Benefit**: Users can Google `VELO-SEC-001` to find solutions.

### 7.2 Auto-Detect Dev-Mode

```rust
fn detect_security_mode() -> SecurityMode {
    if env_is("VELO_ENV", "prod") {
        SecurityMode::Prod
    } else if is_ci_environment() {
        SecurityMode::CI
    } else if is_interactive_terminal() {
        SecurityMode::Dev  // Auto-relax for local development
    } else {
        SecurityMode::Prod  // Conservative default
    }
}
```

| Condition | Result |
|:---|:---|
| `VELO_ENV=prod` | PROD mode (strict) |
| CI environment detected | CI mode (strict + logging) |
| Interactive terminal (tty) | DEV mode (relaxed) |
| Other | PROD mode (conservative) |

### 7.3 pyproject.toml Integration

```toml
# pyproject.toml
[tool.velo.security]
mode = "dev"  # "dev", "ci", "prod"
env_whitelist = ["MY_CUSTOM_VAR", "LEGACY_PATH"]
trusted_paths = ["/opt/my-libs/"]
```

**Benefits**:
- Project-specific configuration
- Git-trackable
- Shareable across team

### 7.4 Security Check Command (Phase 8.x)

```bash
$ velo security check
╔══════════════════════════════════════════════════════════╗
║  VELO Security Audit                                     ║
╠══════════════════════════════════════════════════════════╣
║  Mode: DEVELOPMENT                                       ║
║  Environment Whitelist: 47 entries                       ║
║  Trusted Import Paths: 12 prefixes                       ║
║  ──────────────────────────────────────────────────────  ║
║  ⚠️  Variables that WOULD be filtered in PROD:          ║
║     - MY_CUSTOM_VAR                                      ║
║     - LEGACY_PATH                                        ║
╚══════════════════════════════════════════════════════════╝
```

### 7.5 Failure Diagnostics (Phase 7.2 Enhancement)

When application components fail to start or communicate, Velo MUST provide automatic, first-principles diagnosis:

#### 7.5.1 Handshake Timeout (Implicit Blocking)
If a worker fails to establish the RSGI handshake within the security window (default 500ms):
- **User Perception**: 502/503 Gateway Error.
- **Diagnostic Output**:
  ```
  🚨 [VELO Handshake Timeout] Worker failed to respond within 500ms.
  💡 TIP: This usually means your app has blocking top-level code or manual 'uvicorn.run()' at the module level.
  💡 FIX: Ensure all blocking initialization is inside `if __name__ == '__main__':` or async handlers.
  ```

#### 7.5.2 Import Path Scrubbing
If a worker crashes with `ImportError` due to Environment Shielding:
- **Diagnostic Output**:
  ```
  🚨 [VELO-SEC-002] Import path blocked by Environment Shield.
  💡 TIP: Velo restricts access to absolute paths to prevent supply-chain leaks.
  💡 FIX: Check pyproject.toml [tool.velo.security] trusted_paths.
  ```

### 7.6 Satori Diagnostics (Standardized Actionable Advice)
Every high-level error log MUST follow the **Satori Pattern**:
1. **The Alarm**: Concise error description with searchable code (e.g., `🚨 [VELO-ERR-XXX]`).
2. **The Reason**: Identification of the most likely logical cause (The `💡 TIP`).
3. **The Path**: Immediate, actionable step to resolve the issue (The `💡 FIX`).

### 7.7 Tiered Logging Strategy

| Level | Content | Audience |
|:---|:---|:---|
| **ERROR** | Blocking security issues | All users |
| **WARN** | First-time filter (with guidance) | All users |
| **INFO** | Filter summary (e.g., "2 vars filtered") | Default visible |
| **DEBUG** | Each filtered variable detail | Debugging |

### 7.8 Logging Output Strategy

> [!NOTE]
> Follow cloud-native best practices: stdout by default, structured JSON for aggregation.

#### Default: stdout/stderr

```
┌─────────────────────────────────────────┐
│  Velo Application                       │
│  └── All logs → stdout/stderr           │
└─────────────────────────────────────────┘
        │
        ▼
   Docker/K8s auto-collect → Loki/CloudWatch
```

**Benefits**:
- Container platforms auto-collect
- Log aggregation systems handle filtering
- No log rotation management

#### Optional: JSON Format

```json
{
  "ts": "2026-01-12T21:59:33Z",
  "level": "INFO",
  "msg": "Request processed",
  "request_id": "abc-123",
  "latency_ms": 12,
  "code": "VELO-REQ-200"
}
```

**Configuration**:
```toml
# pyproject.toml
[tool.velo.logging]
format = "json"  # "text" | "json"
```

#### Optional: File Output (Traditional)

```toml
# pyproject.toml
[tool.velo.logging]
output = "file"  # "stdout" | "file" | "both"
log_dir = "./logs"
max_size_mb = 100
max_files = 5
```

**File Structure**:
```
$VELO_LOG_DIR/
└── velo.log              # All levels (rotated)
```

#### Phase Assignment

| Feature | Phase | Priority |
|:---|:---|:---|
| stdout default | 7.2 | ⭐⭐⭐ P1 |
| JSON format option | 7.2 | ⭐⭐ P2 |
| File output option | 8.x | ⭐ P3 |

---

## 8. Performance UX (Operational Transparency)

> [!TIP]
> **Philosophy**: Performance wins should be visible. Users should know *why* Velo is fast (or slow).

### 8.1 Upgrade Nudge (Progressive Enhancement)

When running on older Python versions, gently hint at free performance gains:

```
[VELO:TIP] Running on Python 3.10. Upgrade to Python 3.13+ for ~30% faster requests (Free JIT).
```

### 8.2 JIT Awareness (Python 3.13+)

When JIT is active, celebrate it in the startup banner:

```
╔════════════════════════════════════════════════════════════════╗
║  VELO Runtime: CPython 3.13.1 (JIT: ACTIVE 🚀)                ║
╚════════════════════════════════════════════════════════════════╝
```

### 8.3 Config Doctor (Bottleneck Detection)

If configuration limits performance, warn the user:

```
[VELO:PERF] Performance Warning:
  • UVLOOP_DISABLED: Running with slower asyncio (install uvloop for speed)
  • DEBUG_MODE: Log level is DEBUG (high I/O overhead)
```

### 8.4 Runtime Stats API (Localhost Only)

Internal endpoint `/_velo/stats` for developers to verify optimizations:

```json
{
  "runtime": "cpython",
  "version": "3.13.1",
  "jit_status": "active",
  "optimizations": {
    "memoryview_zero_copy": true,
    "string_interning": true
  }
}
```

### 8.5 Phase Assignment

| Feature | Phase | Priority |
|:---|:---|:---|
| Config Doctor | 7.2 | ⭐⭐ P2 |
| Upgrade Nudge | 8.x | ⭐⭐ P2 |
| JIT Awareness | 8.x | ⭐⭐ P2 |
| Runtime Stats API | 8.x | ⭐ P3 |

