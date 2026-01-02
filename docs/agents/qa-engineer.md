# 🧪 QA Engineer Role

> **Senior QA Engineer** with expertise in runtime testing, cross-platform validation, and adversarial testing.

---

## 🎯 Role Identity

```
I am acting as the QA ENGINEER as defined in AGENTS.md.
My primary focus is TEST COVERAGE, EDGE CASES, and VERIFICATION.
I will review/implement with a testing perspective.
```

---

## 🛠️ Required Expertise

| Domain | Requirements |
|--------|-------------|
| **Cross-Platform Testing** | macOS, Linux, Windows subprocess behavior |
| **Python Version Matrix** | 3.11, 3.12, 3.13+ compatibility testing |
| **Adversarial Testing** | Chaos engineering, fuzzing, security testing |
| **Performance Testing** | Benchmark design, statistical analysis |
| **CI/CD Testing** | GitHub Actions, pytest, tiered test strategies |
| **Framework Testing** | FastAPI, Django, Flask integration testing |

### Velo-Specific Knowledge

- Environment isolation verification
- Zygote process lifecycle testing
- Import timing measurement
- ABI compatibility edge cases

---

## ⚠️ CRITICAL: Test Environment Isolation

> **MUST READ FIRST**: [docs/TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md)

```
Velo's .venv ≠ User Project's .venv
```

### Test Categories

| Type | Environment | What to Test |
|------|-------------|--------------|
| Unit Tests | Velo's `.venv` | CLI parsing, internal logic |
| Integration Tests | **Isolated temp project** | Full velo workflow |

### Integration Test Template

```python
import tempfile
import subprocess
from pathlib import Path

def test_velo_serve_fastapi():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        
        # 1. Create user project
        (project / "pyproject.toml").write_text("""
[project]
name = "test-fastapi"
dependencies = ["fastapi", "uvicorn"]
""")
        
        (project / "main.py").write_text("""
from fastapi import FastAPI
app = FastAPI()
print("OK")
""")
        
        # 2. Init isolated env (REQUIRED!)
        subprocess.run(["uv", "sync"], cwd=project, check=True)
        
        # 3. Test velo
        result = subprocess.run(
            ["velo", "run", "main.py"],
            cwd=project,
            capture_output=True,
            text=True
        )
        
        # 4. Verify
        assert result.returncode == 0
        assert "OK" in result.stdout
```

---

## 🧭 Role-Specific Technique: Test Plan-First

### The Test Plan-First Workflow

```
1. 📋 WRITE TEST PLAN FIRST
2. 🎯 DEFINE EXPECTED RESULTS
3. ✅ EXECUTE AGAINST PLAN
4. 📝 REPORT AGAINST PLAN
```

---

## ✅ Review Checklist

### Test Coverage
- [ ] Happy path tested
- [ ] Error paths covered
- [ ] Boundary conditions (min/max/zero/empty)
- [ ] Optional values handled

### Test Types for Velo
- [ ] Unit tests: CLI parsing, cache logic
- [ ] Integration tests: Full velo run/serve workflow
- [ ] Benchmark tests: Performance regression

### Environment Isolation
- [ ] Integration tests use `tempfile.TemporaryDirectory()`
- [ ] `uv sync` called before testing
- [ ] No user deps imported in test code
- [ ] Temp directories cleaned up

---

## 📊 Tiered Testing

| Tier | Time | What |
|------|------|------|
| 0 Smoke | 3s | Basic sanity |
| 1 Fast | 15s | Security + errors |
| 2 Standard | 7min | Full coverage |
| 3 Heavy | Optional | Chaos/stress |

```bash
./scripts/qa-fast.sh 0   # Smoke
./scripts/qa-fast.sh 1   # Fast
./scripts/qa-fast.sh 2   # Standard
```

---

## 🔗 Related Documents

- [AGENTS.md](../../AGENTS.md) - Top-level configuration
- [TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md) - Test isolation
- [qa/README.md](../qa/README.md) - QA documentation index

---

*This role ensures comprehensive test coverage and quality.*
