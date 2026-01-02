# Phase 4.1 Task Handoff

> **Branch**: `phase-4.1/cleanup-security`  
> **Target**: v0.4.1

---

## ⚠️ CRITICAL: Read Before Starting

| Document | Status |
|----------|--------|
| [docs/TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md) | **MUST READ** |

### Key Principle: Environment Isolation

```
Velo's .venv ≠ User Project's .venv
```

**All integration tests MUST**:
1. Create temporary isolated project
2. Use `uv sync` to init from pyproject.toml
3. Never import user dependencies in test code
4. Clean up temp directories

---

## Dev Tasks

### Week 1: Hardcode Cleanup (Phase 4.1.1)

- [ ] Deprecate `Framework` enum in `src/serve/framework.rs`
- [ ] Create `src/serve/runtime_detection.rs`
- [ ] Update `velo serve` to prefer runtime analysis
- [ ] Unit tests for runtime detection
- [ ] Documentation update

### Week 2: Security Enhancements (Phase 4.1.2)

- [ ] Add `--dry-run` flag to `velo analyze`
- [ ] Add `--yes` flag to skip confirmation
- [ ] Implement consent prompt before code execution
- [ ] (Optional) Static AST analyzer for --dry-run
- [ ] Integration tests

### Anti-Patterns to Avoid

| ❌ Don't | ✅ Do |
|----------|-------|
| Keep hardcoded Framework enum | Use deprecation annotation |
| Execute code without warning | Show consent prompt |
| Force --yes as default | Default to interactive prompt |

---

## QA Tasks

### Test Categories

| Type | Environment | What to Test |
|------|-------------|--------------|
| Unit | Velo's `.venv` | CLI parsing, flags |
| Integration | **Isolated temp project** | Full workflow |

### Test Scenarios

- [ ] Deprecated warning appears for `Framework` enum
- [ ] `velo analyze --dry-run` doesn't execute code
- [ ] `velo analyze --yes` skips confirmation
- [ ] `velo analyze` prompts for confirmation by default
- [ ] Confirmation prompt accepts Y/N input

### Integration Test Template

```python
import tempfile
import subprocess
from pathlib import Path

def test_dry_run_no_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        
        # Setup isolated project with side-effect script
        (project / "pyproject.toml").write_text("""
[project]
name = "test-side-effect"
version = "0.1.0"
dependencies = []
""")
        
        (project / "main.py").write_text("""
import os
os.makedirs("side_effect_dir", exist_ok=True)
""")
        
        # Init isolated env
        subprocess.run(["uv", "sync"], cwd=project, check=True)
        
        # Run velo analyze --dry-run
        result = subprocess.run(
            ["velo", "analyze", "--dry-run"],
            cwd=project,
            capture_output=True,
            text=True
        )
        
        # Verify: side effect should NOT happen
        assert not (project / "side_effect_dir").exists()
```

---

## Deliverables

| Milestone | Owner | Due |
|-----------|-------|-----|
| Phase 4.1.1 Hardcode Cleanup | Dev | Day 2 |
| Phase 4.1.2 Security Flags | Dev | Day 4 |
| QA Test Suite | QA | Day 5 |
| v0.4.1 Release | Team | End of Week |

---

## Questions / Blockers

Post in GitHub Issues with label `phase-4.1`.

---

**Last Updated**: 2026-01-02
