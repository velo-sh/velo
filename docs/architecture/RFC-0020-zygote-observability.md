# RFC-0020: Zygote Observability & Debugging Infrastructure

| Field       | Value                                  |
|-------------|----------------------------------------|
| Status      | Draft                                  |
| Author      | Velo Team                              |
| Created     | 2026-01-09                             |
| Updated     | 2026-01-09                             |
| Depends On  | RFC-0012, RFC-0013                     |

## Abstract

This RFC defines a comprehensive observability and debugging infrastructure for the Velo Zygote system. It addresses the systemic challenges of debugging cross-language (Rust/Python) process orchestration with security shielding, based on lessons learned from production incidents.

## Motivation

### Problem Statement

The Zygote system presents unique debugging challenges:

1. **Cross-Language Opacity**: Errors originating in Python are reported as generic Rust errors (e.g., "Handshake Failed" instead of "AttributeError at line X")
2. **Security Shield Interference**: `ImportShield` and `EnvironmentShield` can block legitimate operations, with failures manifesting far from the root cause
3. **Environment Detection Failures**: CI/dev/prod detection depends on environment variables that may be scrubbed
4. **Fork Tree Complexity**: Workers spawned via Zygote have complex parent-child relationships that are hard to trace
5. **Silent Fallbacks**: "Kinetic Fallback" to cold-start mode happens silently, masking Zygote failures

### Incidents That Motivated This RFC

| Date       | Issue                          | Root Cause                                    | Debug Time |
|------------|--------------------------------|-----------------------------------------------|------------|
| 2026-01-09 | Linux CI failures (13 tests)   | `CI`/`GITHUB_ACTIONS` env vars scrubbed       | 45 min     |
| 2026-01-09 | Zygote startup crash           | `config.loaded_app` AttributeError            | 30 min     |
| 2026-01-09 | Worker detection failure       | ImportShield activated during bootstrap       | 60 min     |

## Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RFC-0020 Observability Stack                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────┐    ┌────────────────┐ │
│  │  Pre-Flight CLI  │    │  Correlation IDs │    │ Failure Bundle │ │
│  │ `velo debug zyg` │    │   (Request UUID) │    │  (Auto-Pack)   │ │
│  └────────┬─────────┘    └────────┬─────────┘    └───────┬────────┘ │
│           │                       │                      │          │
│           ▼                       ▼                      ▼          │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                     Unified Logging Layer                       ││
│  │  • Rust: tracing with request_id                               ││
│  │  • Python: structlog with request_id                           ││
│  │  • Cross-language log correlation                              ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                   Static Analysis Layer                         ││
│  │  • Python: mypy/pyright on velo_zygote                         ││
│  │  • Protocol: JSON Schema for IPC messages                      ││
│  │  • Pre-commit enforcement                                      ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Pre-Flight Check CLI (`velo debug zygote`)

### 1.1 Command Interface

```bash
$ velo debug zygote [OPTIONS]

Options:
  --verbose, -v    Show detailed output for each check
  --json           Output results as JSON (for CI integration)
  --fix            Attempt to fix detected issues automatically
  --timeout <SEC>  Timeout for Zygote startup test (default: 10)
```

### 1.2 Check Sequence

| Step | Check Name              | Validates                                      | Failure Mode                     |
|------|-------------------------|------------------------------------------------|----------------------------------|
| 1    | Environment Detection   | `EnvProfile.detect()` returns correct context  | Wrong context → path blocking    |
| 2    | Security Shield Status  | `ImportShield` inactive, blocked paths correct | `/home` blocked in CI            |
| 3    | Path Validation         | `worker_launcher.py` passes `PathValidator`    | Security Intent Violation        |
| 4    | Python Binary           | Python path valid and executable               | Worker spawn failure             |
| 5    | Socket Test             | Can create/bind UDS socket                     | Permission denied                |
| 6    | Fork Test               | `os.fork()` succeeds, PPID matches             | Fallback to cold-start           |
| 7    | IPC Handshake           | Full Handshake round-trip succeeds             | Protocol version mismatch        |

### 1.3 Implementation

**Rust Side** (`src/cmd/debug.rs`):
```rust
pub fn cmd_debug_zygote(args: &DebugZygoteArgs, config: &VeloConfig) -> Result<()> {
    let preflight = PreflightCheck::new(config);
    
    // Run Python-side preflight via IPC
    let socket_path = tempfile::NamedTempFile::new()?.path().to_path_buf();
    let mut launcher = ZygoteLauncher::new(socket_path.clone());
    
    println!("🔍 Velo Zygote Pre-Flight Check");
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    
    // Step 1-3: Environment checks (before Zygote start)
    preflight.check_environment()?;
    preflight.check_shield_status()?;
    preflight.check_path_validation()?;
    
    // Step 4-7: Zygote lifecycle checks
    launcher.start(&[], None, false, config)?;
    preflight.check_socket(&socket_path)?;
    preflight.check_fork(&socket_path)?;
    preflight.check_handshake(&socket_path)?;
    
    launcher.stop()?;
    println!("✅ Zygote pre-flight check PASSED");
    Ok(())
}
```

**Python Side** (`velo_zygote/preflight.py`):
```python
class PreflightCheck:
    """RFC-0020: Zygote Pre-Flight Diagnostic Suite"""
    
    def run_all(self, verbose: bool = False) -> PreflightResult:
        results = []
        
        # 1. Environment Detection
        results.append(self._check_env_profile())
        
        # 2. Security Shield
        results.append(self._check_shield_status())
        
        # 3. Path Validation
        results.append(self._check_paths())
        
        return PreflightResult(checks=results)
    
    def _check_env_profile(self) -> CheckResult:
        from velo_zygote.env_profile import ENV_PROFILE
        return CheckResult(
            name="Environment Detection",
            passed=True,
            details={
                "os_type": ENV_PROFILE.os_type.name,
                "run_context": ENV_PROFILE.run_context.name,
                "allow_home_path": ENV_PROFILE.allow_home_path,
                "ci_env_present": bool(os.environ.get("CI")),
            }
        )
```

---

## Phase 2: Correlation IDs

### 2.1 Design

Every IPC command will include a `request_id` in the header:

```python
# velo_zygote/ipc.py
@dataclass
class ZygoteCommand:
    request_id: str  # UUID v7 (Time-ordered)
    command_type: str
    payload: dict
```

**Log Format**:
```
# Rust side (tracing)
2026-01-09T12:00:00.000Z INFO [request_id=abc123] Sending Fork command

# Python side (structlog)
2026-01-09T12:00:00.001Z INFO request_id=abc123 Received Fork command
2026-01-09T12:00:00.050Z INFO request_id=abc123 Worker spawned, PID=12345

# Worker side
2026-01-09T12:00:00.100Z INFO request_id=abc123 Worker startup complete
```

### 2.2 Implementation

Add to `constants.toml`:
```toml
# RFC-0020: Observability
observability_enable_correlation_ids = true
observability_log_format = "structured"  # structured, json, text
```

---

## Phase 3: Static Analysis

### 3.1 Python Type Checking (mypy/pyright)

Add to `.pre-commit-config.yaml`:
```yaml
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: v1.8.0
  hooks:
    - id: mypy
      args: [--strict, --ignore-missing-imports]
      files: ^velo_zygote/
      additional_dependencies:
        - types-requests
```

### 3.2 Protocol Schema

Define IPC protocol in JSON Schema (`config/ipc_schema.json`):
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "definitions": {
    "ZygoteCommand": {
      "oneOf": [
        {
          "type": "object",
          "properties": {
            "type": { "const": "Handshake" },
            "version": { "type": "integer" },
            "capabilities": { "type": "array", "items": { "type": "string" } }
          },
          "required": ["type", "version"]
        },
        {
          "type": "object",
          "properties": {
            "type": { "const": "Fork" },
            "script_path": { "type": "string" },
            "args": { "type": "array", "items": { "type": "string" } }
          },
          "required": ["type", "script_path"]
        }
      ]
    }
  }
}
```

---

## Phase 4: Failure Bundle Auto-Pack

### 4.1 Design

When a test fails, automatically capture:
- Zygote log (`~/.local/state/velo/zygote.log`)
- Socket state (`ls -la /tmp/velo-*`)
- Process tree (`ps aux | grep velo`)
- Environment snapshot (`env | grep -E 'VELO|CI|HOME|PATH'`)
- File descriptor state (`ls -la /proc/$PID/fd` on Linux)

### 4.2 Implementation

Add to `tests/qa/conftest.py`:
```python
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    
    if rep.when == "call" and rep.failed:
        bundle_path = Path(f"failure_bundles/{item.name}_{int(time.time())}")
        bundle_path.mkdir(parents=True, exist_ok=True)
        
        # Capture Zygote log
        zygote_log = Path.home() / ".local/state/velo/zygote.log"
        if zygote_log.exists():
            shutil.copy(zygote_log, bundle_path / "zygote.log")
        
        # Capture environment
        (bundle_path / "env.txt").write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(os.environ.items()) if "VELO" in k or k in ["CI", "HOME", "PATH"])
        )
        
        # Capture process tree
        subprocess.run(["ps", "aux"], stdout=open(bundle_path / "ps.txt", "w"))
        
        print(f"\n📦 Failure bundle saved to: {bundle_path}")
```

---

## Phase 5: ImportShield DRY_RUN Mode

### 5.1 Design

Add a `DRY_RUN` mode to `ImportShield` that logs violations without raising exceptions:

```python
class ImportShield:
    _mode: Literal["STRICT", "DRY_RUN", "DISABLED"] = "DISABLED"
    
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("velo_zygote"):
            if self._mode == "STRICT":
                raise ImportError(f"Blocked: {fullname}")
            elif self._mode == "DRY_RUN":
                sys.stderr.write(f"⚠️ [ImportShield DRY_RUN] Would block: {fullname}\n")
        return None
```

Control via environment:
```bash
VELO_IMPORT_SHIELD_MODE=DRY_RUN  # Log warnings only
VELO_IMPORT_SHIELD_MODE=STRICT   # Production mode (default in workers)
VELO_IMPORT_SHIELD_MODE=DISABLED # Development (default in Zygote)
```

---

## Implementation Plan

### Phase 1: Pre-Flight CLI (Priority: P0)

| Task | File | Effort |
|------|------|--------|
| Add `velo debug` subcommand | `src/cmd/debug.rs`, `src/cmd/mod.rs` | 2h |
| Create `PreflightCheck` class | `velo_zygote/preflight.py` | 3h |
| Add tests | `tests/qa/test_preflight.py` | 2h |
| CI integration | `.github/workflows/ci.yml` | 1h |

### Phase 2: Correlation IDs (Priority: P1)

| Task | File | Effort |
|------|------|--------|
| Add `request_id` to IPC protocol | `src/zygote/ipc.rs`, `velo_zygote/ipc.py` | 3h |
| Integrate with Rust tracing | `src/common/logging.rs` | 2h |
| Integrate with Python structlog | `velo_zygote/bootstrap.py` | 2h |

### Phase 3: Static Analysis (Priority: P1)

| Task | File | Effort |
|------|------|--------|
| Add mypy to pre-commit | `.pre-commit-config.yaml` | 1h |
| Add type hints to velo_zygote | `velo_zygote/*.py` | 4h |
| Create IPC JSON Schema | `config/ipc_schema.json` | 2h |

### Phase 4: Failure Bundle (Priority: P2)

| Task | File | Effort |
|------|------|--------|
| Add pytest hook | `tests/qa/conftest.py` | 2h |
| Create bundle collector | `tests/qa/utils/failure_bundle.py` | 3h |

### Phase 5: DRY_RUN Mode (Priority: P2)

| Task | File | Effort |
|------|------|--------|
| Add mode enum to ImportShield | `velo_zygote/shield.py` | 1h |
| Add env var support | `velo_zygote/settings.py` | 1h |
| Add tests | `tests/qa/phase_6_1_1/test_isolation.py` | 1h |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Mean time to debug Zygote failure | ~45 min | < 10 min |
| CI failures due to env detection | ~5/month | 0 |
| Silent fallback incidents | Unknown | 0 (all logged) |
| Type errors caught pre-commit | 0% | 80%+ |

---

## Open Questions

1. **Correlation ID format**: UUID v4 or shorter hash?
2. **Failure bundle retention**: How long to keep in CI artifacts?
3. **mypy strictness level**: `--strict` or relaxed for gradual adoption?

---

## References

- RFC-0012: Hybrid Boundary Governance
- RFC-0013: Kinetic Protocol
- [Trap 276: Zombie Zygote Detection](../qa/methodology.md)
- [Trap 269: macOS Sandbox Alignment](../qa/methodology.md)
