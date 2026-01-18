# Phase 13: `velo test` - Developer Task Checklist

> **RFC**: [RFC-0028](../rfcs/0028-zygote-test-executor.md) (APPROVED)  
> **Branch**: `phase-13/velo-test`  
> **Estimated Effort**: ~3 days

---

## Pre-Implementation Checklist

- [ ] Read RFC-0028 sections 1-11 (Architecture, Hook Points, IPC)
- [ ] Read RFC-0028 section 12 (Council Review P0/P1 blockers)
- [ ] Review existing Zygote implementation: `src/zygote/mod.rs`
- [ ] Review existing IPC protocol: `src/zygote/core_ipc.rs`

---

## Phase 1: CLI Scaffold (0.5 day)

### 1.1 Add `velo test` Command

- [ ] Create `src/cmd/test.rs`
  ```rust
  pub fn cmd_test(args: &[String]) -> Result<()>
  ```
- [ ] Add to `src/cmd/mod.rs`:
  ```rust
  pub mod test;
  pub use test::cmd_test;
  ```
- [ ] Add to `src/cli.rs` USAGE and dispatch:
  ```rust
  "test" => cmd::cmd_test(&args),
  ```

### 1.2 Argument Parsing

- [ ] `velo test <path>` - test path (default: `tests/`)
- [ ] `--workers N` - parallel workers (default: 1)
- [ ] `--tier <N>` - filter by tier marker
- [ ] `--preload <modules>` - CSV of modules to preload
- [ ] `--no-zygote` - disable Zygote (fallback to vanilla pytest)

### 1.3 Basic Integration

- [ ] Invoke `pytest` subprocess with collected args
- [ ] Pass through pytest exit code
- [ ] Unit test: `cargo test cmd::test`

---

## Phase 2: TestCoordinator (1 day)

### 2.1 Create Module Structure

- [ ] Create `src/test/mod.rs`
- [ ] Create `src/test/coordinator.rs`
- [ ] Add to `src/lib.rs`: `pub mod test;`

### 2.2 Implement TestCoordinator

```rust
// src/test/coordinator.rs
pub struct TestCoordinator {
    zygote: ZygoteLauncher,
    pool: ConnectionPool<ZygoteStream>, // P1-3 mitigation
    results: mpsc::Receiver<TestResult>,
}

impl TestCoordinator {
    pub fn new(config: &VeloConfig) -> Result<Self>;
    pub fn spawn_workers(&mut self, n: usize) -> Result<()>;
    pub fn dispatch(&self, test_id: &str) -> Result<()>;
    pub fn aggregate(&self) -> TestReport;
}
```

### 2.3 Fork Safety (P0 Critical)

- [ ] Verify Zygote is single-threaded before fork (P0-2)
- [ ] Set `PYTHONDONTWRITEBYTECODE=1` in child env (P1-2)
- [ ] Add `request_id` correlation for test dispatch

---

## Phase 3: pytest-velo Plugin (1 day)

### 3.1 Create Plugin Structure

- [ ] Create `python/pytest_velo/__init__.py`
- [ ] Create `python/pytest_velo/plugin.py`

### 3.2 Implement pytest Hooks

```python
# python/pytest_velo/plugin.py

def pytest_addoption(parser):
    parser.addoption("--velo", action="store_true")
    parser.addoption("--velo-preload", default="")

def pytest_configure(config):
    if config.option.velo:
        # Start Zygote, preload modules
        pass

def pytest_unconfigure(config):
    # Shutdown Zygote
    pass

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if item.config.option.velo:
        return run_in_zygote_fork(item)
    return None
```

### 3.3 Fork Safety Hooks (P0 Critical)

- [ ] Implement `pytest_velo_fork_reinit` hook (P0-1)
- [ ] Call `atexit._clear()` in child (P0-3)
- [ ] Use `os._exit()` not `sys.exit()` (P0-3)

### 3.4 xdist Mutual Exclusivity (P1-1)

- [ ] Detect `-n` flag in `pytest_configure`
- [ ] Emit warning and disable `--velo` if xdist detected

### 3.5 Register Entry Point

- [ ] Add to `pyproject.toml`:
  ```toml
  [project.entry-points."pytest11"]
  velo = "pytest_velo.plugin"
  ```

---

## Definition of Done

- [ ] `cargo test --all` passes
- [ ] `velo test tests/qa/phase5/test_bench.py` runs successfully
- [ ] Fork latency < 2ms (use `--benchmark` mode)
- [ ] All P0 mitigations implemented
- [ ] Code reviewed by Architect

---

**Handoff to QA after Phase 3 completion.**
