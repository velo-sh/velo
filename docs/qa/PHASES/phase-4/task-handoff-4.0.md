# Phase 4.0 Task Handoff

> **Branch**: `phase-4.0/velo-analyze`  
> **RFC**: `docs/rfcs/0004-phase-4-analyze.md`  
> **Target**: v0.4.0

---

## ⚠️ CRITICAL: Read Before Starting

| Document | Status |
|----------|--------|
| [docs/TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md) | **MUST READ** |
| [docs/rfcs/0004-phase-4-analyze.md](../rfcs/0004-phase-4-analyze.md) | RFC |

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

### Week 1: Basic Analysis (Phase 4.0.1)

- [ ] Create `src/cmd/analyze.rs`
- [ ] Reuse `--profile` output parsing from `profile.rs`
- [ ] Implement visual bar chart output (Bash colors)
- [ ] Add `--slow-threshold-ms` flag (default: 100ms)
- [ ] Unit tests for analysis logic

### Week 2: Recommendations (Phase 4.0.2)

- [ ] Implement preload suggestion algorithm
- [ ] Read `[tool.velo]` from pyproject.toml
- [ ] Generate preload config with `--fix`
- [ ] Documentation update
- [ ] Integration tests

### Anti-Patterns to Avoid

| ❌ Don't | ✅ Do |
|----------|-------|
| Hardcode framework list | Analyze runtime import times |
| Create `velo.toml` | Use `pyproject.toml [tool.velo]` |
| Guess preload modules | Measure with `--profile` |

---

## QA Tasks

### Test Categories

| Type | Environment | What to Test |
|------|-------------|--------------|
| Unit | Velo's `.venv` | CLI parsing, analysis logic |
| Integration | **Isolated temp project** | Full analyze workflow |

### Test Scenarios

- [ ] `velo analyze` on FastAPI project
- [ ] `velo analyze` on Django project
- [ ] `velo analyze` on DataScience project (numpy, pandas)
- [ ] `velo analyze --fix` writes to pyproject.toml
- [ ] `velo analyze` with no slow imports
- [ ] `velo analyze` with custom `--slow-threshold-ms`

### Integration Test Template

```python
import tempfile
import subprocess
from pathlib import Path

def test_analyze_fastapi():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        
        # Setup isolated project
        (project / "pyproject.toml").write_text("""
[project]
name = "test-fastapi"
version = "0.1.0"
dependencies = ["fastapi", "uvicorn"]
""")
        
        (project / "main.py").write_text("""
from fastapi import FastAPI
app = FastAPI()
""")
        
        # Init isolated env
        subprocess.run(["uv", "sync"], cwd=project, check=True)
        
        # Run velo analyze
        result = subprocess.run(
            ["velo", "analyze"],
            cwd=project,
            capture_output=True,
            text=True
        )
        
        # Verify
        assert result.returncode == 0
        assert "fastapi" in result.stdout
```

---

## Deliverables

| Milestone | Owner | Due |
|-----------|-------|-----|
| Phase 4.0.1 Basic Analysis | Dev | Week 1 |
| Phase 4.0.2 Recommendations | Dev | Week 2 |
| QA Test Suite | QA | Week 2 |
| v0.4.0 Release | Team | End of Week 2 |

---

## Questions / Blockers

Post in GitHub Issues with label `phase-4.0`.

---

**Last Updated**: 2026-01-02
