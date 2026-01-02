# Phase 4.1 Task Handoff

> **Branch**: `phase-4.1/cleanup-security`  
> **RFC**: `docs/rfcs/0005-phase-4.1-cleanup-security.md`  
> **Target**: v0.4.1

---

## CRITICAL: Read Before Starting

| Document | Status |
|----------|--------|
| [docs/rfcs/0005-phase-4.1-cleanup-security.md](../rfcs/0005-phase-4.1-cleanup-security.md) | **MUST READ** |
| [docs/TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md) | Reference |

---

## Dev Tasks

### Day 1: DELETE framework.rs + velo.toml legacy

**Part A: framework.rs**
- [ ] Delete `src/serve/framework.rs`
- [ ] Update `src/serve/mod.rs` (remove framework export)
- [ ] Update `src/serve/runner.rs` (remove framework import/usage)
- [ ] Verify: `cargo build` passes

**Part B: velo.toml legacy cleanup**
- [ ] Remove `velo.toml` generation in `src/cmd/zygote.rs:141-143`
- [ ] Update `src/zygote/auto_config.rs` (remove `to_toml()` or redirect to pyproject.toml)
- [ ] Update docs: `docs/zygote.md`, `docs/rfcs/0002-*.md`
- [ ] Update tests: `test_phase3_*.py` files
- [ ] Verify: `cargo test` passes

### Day 2-3: Split analyze.rs

Split 854-line file into module:

```
src/cmd/analyze.rs
       ↓
src/cmd/analyze/
├── mod.rs     # Entry point + cmd_analyze()
├── args.rs    # AnalyzeArgs + parse_args()
├── config.rs  # VeloConfig + TOML parsing
├── display.rs # display_analysis() + colors
└── report.rs  # save_json_report() + update_pyproject_toml()
```

- [ ] Create `src/cmd/analyze/` directory
- [ ] Extract `args.rs`
- [ ] Extract `config.rs`
- [ ] Extract `display.rs`
- [ ] Extract `report.rs`
- [ ] Update `mod.rs` with re-exports
- [ ] Verify: all 61 tests pass

### Day 4: Security Flags

- [ ] Add `--dry-run` flag to AnalyzeArgs
- [ ] Add `--yes` / `-y` flag to AnalyzeArgs
- [ ] Implement consent prompt in cmd_analyze()
- [ ] Unit tests for new flags
- [ ] Integration tests

---

## QA Tasks

### Test Scenarios

- [ ] `cargo build` passes after framework.rs deletion
- [ ] All 61 unit tests pass
- [ ] `velo analyze --help` shows --dry-run and --yes flags
- [ ] `velo analyze --dry-run` does NOT execute code
- [ ] `velo analyze --yes` skips confirmation
- [ ] Default `velo analyze` prompts for confirmation

### Regression Tests

- [ ] `velo run` still works
- [ ] `velo serve` still works (without framework detection)
- [ ] `velo info` still works

---

## Deliverables

| Milestone | Owner | Due |
|-----------|-------|-----|
| DELETE framework.rs | Dev | Day 1 |
| Split analyze.rs | Dev | Day 3 |
| Security flags | Dev | Day 4 |
| QA Sign-off | QA | Day 5 |
| v0.4.1 Release | Team | Day 5 |

---

## Questions / Blockers

Post in GitHub Issues with label `phase-4.1`.

---

**Last Updated**: 2026-01-02
