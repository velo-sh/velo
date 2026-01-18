# Phase 13: `velo test` - Developer Task Checklist

> **RFC**: [RFC-0028](../rfcs/0028-zygote-test-executor.md) (APPROVED)  
> **Branch**: `phase-13/velo-test`  
> **Estimated Effort**: ~3 days

---

## Pre-Implementation Checklist ✅

- [x] Read RFC-0028 sections 1-11 (Architecture, Hook Points, IPC)
- [x] Read RFC-0028 section 12 (Council Review P0/P1 blockers)
- [x] Review existing Zygote implementation: `src/zygote/mod.rs`
- [x] Review existing IPC protocol: `src/zygote/core_ipc.rs`

---

## Phase 1: CLI Scaffold ✅ (Commit: 7d4fa92)

### 1.1 Add `velo test` Command

- [x] Create `src/cmd/vtest.rs` (renamed from test.rs for searchability)
- [x] Add to `src/cmd/mod.rs`
- [x] Add to `src/cli.rs` USAGE and dispatch

### 1.2 Argument Parsing

- [x] `velo test <path>` - test path (default: `tests/`)
- [x] `--workers N` - parallel workers (default: 1)
- [x] `--tier <N>` - filter by tier marker
- [x] `--preload <modules>` - CSV of modules to preload
- [x] `--zygote` - enable Zygote (opt-in, requires plugin)

### 1.3 Basic Integration

- [x] Invoke `pytest` subprocess via `uv run pytest`
- [x] Pass through pytest exit code

---

## Phase 2: TestCoordinator ✅ (Commit: TBD)

### 2.1 Module Structure

- [x] Create `src/test/mod.rs`
- [x] Create `src/test/coordinator.rs`
- [x] Add to `src/lib.rs`: `pub mod test;`

### 2.2 TestCoordinator Implementation

```rust
// src/test/coordinator.rs
pub struct TestCoordinator { ... }  // ✅ Implemented

impl TestCoordinator {
    pub fn new(config: &VeloConfig) -> Result<Self>;  // ✅
    pub fn ensure_zygote(&mut self, preload: &[&str]) -> Result<()>;  // ✅
    pub fn add_tests(&mut self, test_ids: Vec<String>);  // ✅
    pub fn dispatch(&mut self, test_id: &str) -> Result<()>;  // ✅ (stub)
    pub fn run_all(&mut self) -> Result<TestReport>;  // ✅
    pub fn shutdown(&mut self) -> Result<()>;  // ✅
}
```

### 2.3 Tests

- [x] `test_coordinator_creation` - passes
- [x] `test_report_defaults` - passes
- [x] `test_report_with_failure` - passes

### 2.4 Fork Safety (P0 Critical)

- [x] Verify Zygote is single-threaded before fork (P0-2) - handled in plugin
- [x] Set `PYTHONDONTWRITEBYTECODE=1` in child env (P1-2) - in pytest_configure

---

## Phase 3: pytest-velo Plugin ✅ (Commit: 7d4fa92)

### 3.1 Create Plugin Structure

- [x] Create `pytest_velo/__init__.py`
- [x] Create `pytest_velo/plugin.py`

### 3.2 Implement pytest Hooks

- [x] `pytest_addoption` - `--velo`, `--velo-preload`
- [x] `pytest_configure` - validate xdist, set PYTHONDONTWRITEBYTECODE
- [x] `pytest_unconfigure` - cleanup
- [x] `pytest_runtest_protocol` - fork execution hook

### 3.3 Fork Safety Hooks (P0 Critical)

- [x] Implement `pytest_velo_fork_reinit` hook (P0-1)
- [x] Call `atexit._clear()` in child (P0-3)
- [x] Use `os._exit()` not `sys.exit()` (P0-3)

### 3.4 xdist Mutual Exclusivity (P1-1)

- [x] Detect `-n` flag in `pytest_configure`
- [x] Raise `UsageError` if both `--velo` and `-n` enabled

### 3.5 Register Entry Point

- [x] Add to `pyproject.toml`:
  ```toml
  [project.entry-points."pytest11"]
  velo = "pytest_velo.plugin"
  ```

### 3.6 Tests

- [x] `test_phase13_pytest_velo.py` - 10 tests, all pass

---

## Definition of Done

- [x] `cargo test --all` passes (281 tests)
- [x] `velo test tests/qa/test_phase13_pytest_velo.py` runs successfully
- [ ] Fork latency < 2ms (actual: ~2.3ms, within 5ms tolerance)
- [x] All P0 mitigations implemented
- [ ] Code reviewed by Architect

---

**Last Updated**: 2026-01-18
