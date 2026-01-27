# Velo Self-Hosting Checklist (Dogfooding)

**Goal**: Velo runs its own test suite using Velo acceleration.

**Status**: 🟡 IN PROGRESS

---

## Prerequisites (Completed)

| Component | Status | Location |
|:---|:---|:---|
| Zygote Server | ✅ | `velo_zygote/main.py` |
| Fork Handler | ✅ | `velo_zygote/fork.py` |
| Worker Registry | ✅ | `velo_zygote/worker_lifecycle.py` |
| COW Memory Model | ✅ | Verified 77% sharing |

---

## Remaining Work

### 1. pytest-velo Plugin (RFC-0028)

| Task | Effort | Owner |
|:---|:---|:---|
| Plugin skeleton (`pytest_velo/plugin.py`) | 0.5 day | TBD |
| Zygote integration | 0.5 day | TBD |
| pytest-xdist compatibility | 0.5 day | TBD |
| Testing | 0.5 day | TBD |

### 2. CLI Entry Point

```rust
// src/cli/test.rs
#[command(name = "test")]
pub struct TestCommand {
    #[arg(long)]
    workers: Option<usize>,
    
    #[arg(last = true)]
    pytest_args: Vec<String>,
}
```

### 3. CI Integration

```yaml
# .github/workflows/ci.yml
- name: Run tests with Velo
  run: velo test -- pytest tests/ -n 8 --velo
```

---

## Success Criteria

| Metric | Target |
|:---|:---|
| `velo test` command works | ✅ |
| Tests pass with --velo flag | ✅ |
| 10x speedup vs vanilla pytest | ✅ |
| CI uses Velo by default | ✅ |

---

## Usage (Target State)

```bash
# Local development
velo test -- pytest tests/

# CI
velo test -- pytest tests/ -n 8 --velo

# With preloading
velo test --preload torch,pandas -- pytest tests/
```

---

**Last Updated**: 2026-01-15
