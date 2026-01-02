# Architect Handover: velo.toml Cleanup

> **Date**: 2026-01-02  
> **Branch**: `phase-4.1/cleanup-security`  
> **Commits**: `5f4f546`, `1d4a842`

---

## Summary

Cleaned up all `velo.toml` legacy references. Configuration now uses standard `pyproject.toml [tool.velo]` format per Python ecosystem best practices.

---

## For Developer

### Code Changes Made

| File | Change |
|------|--------|
| `src/zygote/auto_config.rs` | `to_toml()` now outputs `[tool.velo]` format instead of `[zygote]` |
| `src/cmd/zygote.rs` | `auto-config` command now updates `pyproject.toml` instead of creating `velo.toml` |

### Behavior Changes

| Before | After |
|--------|-------|
| `velo zygote auto-config` creates `velo.toml` | Updates `pyproject.toml` with `[tool.velo]` section |
| Config format: `[zygote]` | Config format: `[tool.velo]` |

### Remaining Phase 4.1 Tasks (For Dev)

- [ ] DELETE `src/serve/framework.rs`
- [ ] Update `src/serve/mod.rs` (remove framework export)
- [ ] Update `src/serve/runner.rs` (remove framework import/usage)
- [ ] Split `src/cmd/analyze.rs` into 5 files
- [ ] Add `--dry-run`, `--yes` flags to analyze command
- [ ] Implement consent prompt

---

## For QA

### Files Modified

**Rust Source (2 files)**:
- `src/zygote/auto_config.rs`
- `src/cmd/zygote.rs`

**Documentation (5 files)**:
- `docs/zygote.md` - Output example updated
- `docs/rfcs/0002-phase-3-zygote.md` - Config format section
- `docs/rfcs/0002-phase-3-dev-guide.md` - Milestone check
- `docs/qa/phase-3-test-matrix.md` - CFG-003, CFG-004
- `docs/qa/DEF-003-zygote-prewarm.md` - REQ-2

**Test Files (4 files)**:
- `tests/qa/test_phase3_harness.py` - `create_velo_config()` method
- `tests/qa/test_phase3_config_chaos.py` - All config tests
- `tests/qa/test_phase3_arch_requirements.py` - CFG-003 test
- `tests/qa/test_phase3_5_agent_c_security.py` - SEC-CFG-001 test

### Verification Checklist

- [ ] `cargo build` passes
- [ ] `cargo test` passes (72 tests)
- [ ] `velo zygote auto-config` updates `pyproject.toml` (not `velo.toml`)
- [ ] `velo analyze --fix` writes `[tool.velo]` section
- [ ] No references to `velo.toml` in codebase (except historical docs)

### Regression Tests

Run these to verify no breakage:

```bash
# Unit tests
cargo test

# QA tests (if pytest available)
pytest tests/qa/test_phase3_*.py -v
pytest tests/qa/test_phase4_*.py -v
```

---

## Architecture Decision

| Decision | Rationale |
|----------|-----------|
| Use `pyproject.toml [tool.velo]` | Standard Python tool config (like pytest, black, ruff) |
| DELETE `velo.toml` support | Avoid config file fragmentation |
| No migration path | Clean break - legacy `velo.toml` will be ignored |

---

**Architect Sign-off**: ✅ Reviewed and approved  
**Last Updated**: 2026-01-02
