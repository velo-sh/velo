# DEF-61-003: Bundle Test Compilation Failure (API Mismatch)

**Priority:** P1
**Status:** OPEN
**Reporter:** QA Agent (Round 3 Verification)
**Assignee:** Developer

---

## Summary
`tests/bundle_build_test.rs` fails to compile after CLI refactor. 
The test imports `cmd_bundle_build` and `cmd_bundle_inspect` which no longer exist.

## Reproduction
```bash
cargo test
# error[E0432]: unresolved imports `velo::cmd::bundle::cmd_bundle_build`, `velo::cmd::bundle::cmd_bundle_inspect`
```

## Expected Behavior
All Rust tests should compile and pass after refactor.

## Actual Behavior
```
error[E0432]: unresolved imports `velo::cmd::bundle::cmd_bundle_build`, `velo::cmd::bundle::cmd_bundle_inspect`
 --> tests/bundle_build_test.rs:8:29
  |
8 |     use velo::cmd::bundle::{cmd_bundle_build, cmd_bundle_inspect, read_bundle_info};
  |                             ^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^
```

## Root Cause Analysis
Developer refactored `src/cmd/bundle.rs`:
- `cmd_bundle_build` → renamed or removed
- `cmd_bundle_inspect` → renamed or removed
- New entry point is `cmd_bundle()`

Test file not updated to match new API.

## Suggested Fix
Update `tests/bundle_build_test.rs` to use new function names:
- `cmd_bundle_build_impl` (if exposed)
- Or call `cmd_bundle()` with appropriate args

## Impact
- **BLOCKS** `cargo test` (all integration tests)
- Does NOT block Python QA tests

---
**QA Signature:** Velo QA Working Group
**Date:** 2026-01-04
