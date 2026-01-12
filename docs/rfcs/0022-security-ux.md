# RFC-0022: Security UX Improvements (Dev-Mode & Startup Feedback)

**Status**: DRAFT
**Author**: Architect
**Date**: 2026-01-12
**Priority**: P1 (User Experience Critical)

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

### 7.5 Failure Diagnostics (Phase 8.x)

When application fails to start, provide automatic diagnosis:

```
[VELO:DIAG] Application failed to start.
            Possible causes:
            1. Import path blocked - check VELO_LOG=debug
            2. Environment variable filtered - see pyproject.toml
            3. Dependency conflict - run 'velo deps check'
            
            Run 'velo doctor' for full diagnostics.
```

### 7.6 Tiered Logging Strategy

| Level | Content | Audience |
|:---|:---|:---|
| **ERROR** | Blocking security issues | All users |
| **WARN** | First-time filter (with guidance) | All users |
| **INFO** | Filter summary (e.g., "2 vars filtered") | Default visible |
| **DEBUG** | Each filtered variable detail | Debugging |

### 7.7 Logging Output Strategy

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
