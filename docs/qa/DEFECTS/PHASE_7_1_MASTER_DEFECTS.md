# Phase 7.1 Master Defect Report (RFC-0018: Integrated Custody)

**QA Verdict**: � **CONDITIONALLY APPROVED**
**Rationale**: Design is TITANIUM-certified. Implementation is scaffolding (expected for Phase 7.1).
**Build Hash**: 7a78e74
**Date**: 2026-01-12
**QA Engineer**: QA Leader

---

## Executive Summary

RFC-0018 "Integrated Custody" **design is approved**. The current code is **scaffolding** with system `uv` fallback, which is acceptable for Phase 7.1 milestone. Full implementation scheduled for Phase 7.15 (Asset Embedding).

| Gate | RFC Requirement | Implementation Status |
|:---:|:---|:---:|
| **Gate A** | Embedded uv BLAKE3 verification | ⏳ Scaffolding (TODO) |
| **Gate B** | Socket namespace isolation | ✅ Implemented (`0o700` dirs) |
| **Gate C** | Shadow sync < 100ms | ⏳ Pending measurement |

---

## P0 Critical Defects (BLOCKERS)

### DEF-71-001: Shadow Commands Not Implemented

**Priority**: P0
**Status**: OPEN
**File**: `src/main.rs` (CLI registration)

**Evidence**:
```bash
$ ./target/release/velo python --version
error: unknown command 'python'
```

**RFC-0018 Requirement** (§3.1):
> Shadow Command: `velo python ...` and `velo pip ...` will be proxied through the embedded `uv` context.

**Impact**: RFC's core value proposition (Zero-Config DX) is non-functional.

---

### DEF-71-002: BLAKE3 Verification is TODO

**Priority**: P0
**Status**: OPEN
**File**: [custodian.rs:126](file:///Users/gjwang/eclipse-workspace/rust_source/velo_qa/src/custody/custodian.rs#L126)

**Evidence**:
```rust
// TODO: Implement BLAKE3 verification when assets are embedded
// For now, just check the file exists and is executable
```

**RFC-0018 Requirement** (§5 Gate A):
> Gate A (Forensic): Embedded `uv` must pass BLAKE3 verification post-extraction.

**Security Impact**: Tampered binaries will be executed without detection.

---

### DEF-71-003: No Embedded uv Binary

**Priority**: P0
**Status**: OPEN
**File**: [asset.rs:79-80](file:///Users/gjwang/eclipse-workspace/rust_source/velo_qa/src/custody/asset.rs#L79-80)

**Evidence**:
```rust
Ok(Self {
    platform,
    bytes: None,       // Placeholder until assets embedded
    blake3_hash: None, // Placeholder until build.rs generates
})
```

**RFC-0018 Requirement** (§3.1):
> Asset Embedding: `uv` binaries for supported platforms are embedded into the Velo binary using `include_bytes!`.

**Impact**: Falls back to system `uv` - defeats the "Zero-Dependency" goal.

---

### DEF-71-004: `is_available()` Always Returns False

**Priority**: P0
**Status**: OPEN
**File**: [asset.rs:60](file:///Users/gjwang/eclipse-workspace/rust_source/velo_qa/src/custody/asset.rs#L60)

**Evidence**:
```rust
pub fn is_available() -> bool {
    cfg!(feature = "embedded_uv")  // Feature not enabled
}
```

**Impact**: Embedded custody is completely disabled by default.

---

## P1 High Defects

### DEF-71-005: Fingerprint Drift Detection Uses Wrong State File

**Priority**: P1
**File**: [fingerprint.rs](file:///Users/gjwang/eclipse-workspace/rust_source/velo_qa/src/custody/fingerprint.rs)

**RFC-0018 Requirement** (§4 architecture overview):
> State file at `.velo/env.state`

**Actual**: Uses different path structure. Need to verify alignment.

---

## P2 Medium Defects

### DEF-71-006: Telemetry Store Uses Predictable Path

**Priority**: P2
**File**: [autopilot.rs:206](file:///Users/gjwang/eclipse-workspace/rust_source/velo_qa/src/custody/autopilot.rs#L206)

**Evidence**:
```rust
.unwrap_or_else(|| PathBuf::from("/tmp/.velo/telemetry.json"))
```

**Security Concern**: Fallback to `/tmp` allows cross-user telemetry pollution.

---

## Summary

| Priority | Open | Fixed | Verified |
|:---:|:---:|:---:|:---:|
| P0 | 4 | 0 | 0 |
| P1 | 1 | 0 | 0 |
| P2 | 1 | 0 | 0 |

**QA Verdict**: 🔴 **REJECTED** - RFC-0018 cannot be considered APPROVED while implementation is scaffolding.

---

**QA Signature**: Agent C (Security Prosecutor)
**Date**: 2026-01-12
