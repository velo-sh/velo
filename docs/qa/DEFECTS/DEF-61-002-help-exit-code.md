# DEF-61-002: CLI --help Exit Code Non-Standard

**Priority:** P3
**Status:** OPEN
**Reporter:** Agent A (E2E Testing)
**Assignee:** Developer

---

## Summary
`velo serve --help` returns exit code 1 instead of standard exit code 0.

## Reproduction
```bash
./target/release/velo serve --help
echo $?  # Returns 1 instead of 0
```

## Expected Behavior
CLI `--help` flag should return exit code 0 (standard Unix convention).

## Actual Behavior
Returns exit code 1 with help text printed to stderr.

## Root Cause Analysis
The `clap` argument parser in `src/cmd/serve.rs` uses a custom error handler that treats all non-successful parses (including `--help`) as errors.

## Suggested Fix
Modify `cmd_serve` to explicitly handle `--help` using clap's built-in help display, which returns exit code 0.

## Impact
- **Test Impact**: E2E tests must check stdout+stderr instead of asserting exit code 0.
- **User Impact**: Scripts that check exit codes may incorrectly interpret `--help` as failure.

---
**QA Signature:** Velo QA Working Group
**Date:** 2026-01-04
