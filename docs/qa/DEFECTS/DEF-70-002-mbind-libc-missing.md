# DEF-70-002: libc::mbind Not Found - CI Compilation Failure

> [!CAUTION]
> **TITANIUM BLOCKER** - CI Pipeline is DEAD. No code can be merged until this is fixed.

**Severity**: 🔴 P0 TITANIUM BLOCKER  
**Owner**: Developer Team  
**Reporter**: QA Agent  
**Date**: 2026-01-07  
**Status**: OPEN - BLOCKING ALL CI  

## Summary

**Developer shipped code that does not compile on CI.**

The `src/shm/registry.rs` uses `libc::mbind` and `libc::MPOL_MF_STRICT` which **DO NOT EXIST** in the libc crate. This passed local macOS builds but **fails on Linux CI**.

## Evidence

```
CI Run: 20777083595
Branch: phase-7.0/memory-gravity
Job: Clippy

error[E0425]: cannot find function `mbind` in crate `libc`
   --> src/shm/registry.rs:104:27
    |
104 |                     libc::mbind(
    |                           ^^^^^ help: a function with a similar name exists: `bind`

error[E0425]: cannot find value `MPOL_MF_STRICT` in crate `libc`
   --> src/shm/registry.rs:110:31
    |
110 |                         libc::MPOL_MF_STRICT,
    |                               ^^^^^^^^^^^^^^ not found in `libc`
```

## Root Cause

The `libc` crate does not export `mbind()` or `MPOL_*` constants. These are NUMA-specific syscalls that require either:
1. Manual syscall definition via `libc::syscall(SYS_MBIND, ...)`
2. Use of the `nix` crate which wraps these syscalls

## Impact

- **CI is completely blocked** - no builds can pass
- QA Phase 7.0 tests cannot run in GitHub Actions
- All 5 recent CI runs on phase-7.0 branch failed

## QA Status

**Local Docker CI**: ✅ 15 passed, 1 skipped (Python tests work)  
**GitHub Actions CI**: ❌ Blocked by Rust compilation error

## Required Fix (Developer)

```rust
// Option 1: Use libc::syscall directly
const SYS_MBIND: libc::c_long = 237; // x86_64
const MPOL_BIND: i32 = 2;
const MPOL_MF_STRICT: u32 = 1;

let ret = unsafe {
    libc::syscall(SYS_MBIND, ptr, size, MPOL_BIND, &mask, maxnode, MPOL_MF_STRICT)
};

// Option 2: Use nix crate (recommended)
// Add `nix = { version = "0.27", features = ["mman"] }` to Cargo.toml
```

## Verification

After fix, run:
```bash
cargo clippy -- -D warnings
```

---

> **QA Note**: QA does not modify business code. This defect is assigned to Developer team for resolution.
