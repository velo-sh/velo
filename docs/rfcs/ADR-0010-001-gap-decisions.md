# ADR-0010-001: Phase 6.1 Gap Analysis Decisions

> **Status**: APPROVED  
> **Date**: 2026-01-04  
> **From**: Architect  
> **To**: Developer  
> **RFC**: [0010-phase-6.1-serve-analyze.md](./0010-phase-6.1-serve-analyze.md)

---

## Context

Developer identified implementation gaps during RFC-0010 review. This ADR documents Architect decisions.

---

## Decisions

### D1: App Validation Location

**Question**: CLI layer vs `run_server()` internal?

**Decision**: **CLI layer** (`src/cmd/serve.rs`)

**Rationale**: Fail-fast principle. Reject malicious input before ANY subprocess work.

**Implementation**:
```rust
// src/cmd/serve.rs - validate BEFORE calling run_server()
fn validate_app_target(app: &str) -> Result<(), ServeError> {
    let forbidden = ['|', '&', ';', '$', '`', '\\', '"', '\'', '<', '>', '\n'];
    if app.chars().any(|c| forbidden.contains(&c)) {
        return Err(ServeError::ShellMetacharacters { app: app.to_string() });
    }
    Ok(())
}
```

---

### D2: Health Server Priority

**Question**: v0.6.1 required or v0.6.2?

**Decision**: **v0.6.1 MUST**

**Rationale**: RFC §4.7.1 is P0. Cloud Native deployments are primary target.

**Implementation**:
- Use `tiny_http` crate (per §4.9.5)
- Separate thread (not tokio)
- Minimal responses: `/healthz` → `200 OK`, `/readyz` → `200 OK` or `503`

---

### D3: Environment Sanitization Scope

**Question**: Remove all or configurable?

**Decision**: **Remove ALL dangerous vars. NOT configurable.**

**Rationale**: Security invariants are non-negotiable per §4.10.5.

**Implementation**:
```rust
fn sanitize_subprocess_env(cmd: &mut Command) {
    let dangerous = [
        "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
        "LD_PRELOAD", "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",  // macOS
    ];
    for var in &dangerous {
        cmd.env_remove(var);
    }
}
```

---

### D4: Signal Reset on macOS

**Decision**: **v0.6.1 MUST** for `#[cfg(target_os = "macos")]`

**Implementation**:
```rust
#[cfg(target_os = "macos")]
unsafe {
    cmd.pre_exec(|| {
        libc::signal(libc::SIGINT, libc::SIG_DFL);
        libc::signal(libc::SIGTERM, libc::SIG_DFL);
        Ok(())
    });
}
```

---

### D5: JSON Logging

**Decision**: **v0.6.1 basic implementation**

**Format**:
```json
{"timestamp":"2026-01-04T09:47:19Z","level":"info","msg":"Server started","timing_ms":8}
```

---

## Implementation Order

| Priority | Task | Blocking |
|----------|------|----------|
| 1 | SEC-P0-001 Shell metachar rejection | Yes - blocks spawn |
| 2 | SEC-P0-005 Env sanitization | No |
| 3 | MAC-P0-002 Signal reset | Platform-specific |
| 4 | CN-P0-001 Health server | No - parallel OK |
| 5 | CN-P0-003 JSON logging | No |

---

## Acceptance Criteria

- [ ] Shell metacharacters rejected at CLI layer
- [ ] Health endpoints respond correctly
- [ ] Dangerous env vars removed before spawn
- [ ] No zombie workers on macOS Ctrl+C
- [ ] `--log-format json` produces valid JSON

---

**Architect Sign-off**: ✅ All decisions are final for v0.6.1
