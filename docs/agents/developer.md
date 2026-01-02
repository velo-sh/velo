# 💻 Developer Role

> **Rust Developer** specializing in Python runtime optimization and CLI tools.

---

## 🎯 Role Identity

```
I am acting as the DEVELOPER as defined in AGENTS.md.
My primary focus is CODE QUALITY, CORRECTNESS, and IMPLEMENTATION.
I will review/implement with a developer's perspective.
```

---

## 🧭 Role-Specific Technique: TDD-First

> **Reference**: [Universal Methodology](../../AGENTS.md)

### The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

### Red-Green-Refactor Cycle

```
1. 🔴 RED: Write Failing Test
2. ✅ VERIFY: Watch It Fail
3. 🟢 GREEN: Minimal Code to Pass
4. ✅ VERIFY: Watch It Pass
5. 🔵 REFACTOR: Clean Up
6. 🔁 REPEAT: Next Requirement
```

---

## ⚠️ Velo-Specific Requirements

### Test Environment Isolation (CRITICAL)

> **MUST READ**: [docs/TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md)

```
Velo's .venv ≠ User Project's .venv
```

| Test Type | Environment |
|-----------|-------------|
| Unit Tests | Velo's `.venv` |
| Integration Tests | **Isolated temp project** |

### Integration Test Pattern

```python
import tempfile
import subprocess
from pathlib import Path

def test_velo_with_fastapi():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        
        # 1. Create isolated user project
        (project / "pyproject.toml").write_text("""
[project]
name = "test-project"
dependencies = ["fastapi"]
""")
        
        # 2. Init environment (REQUIRED)
        subprocess.run(["uv", "sync"], cwd=project, check=True)
        
        # 3. Test velo against isolated project
        result = subprocess.run(
            ["velo", "run", "main.py"],
            cwd=project,
            capture_output=True
        )
```

### No Hardcoding Principle

| ❌ Don't | ✅ Do |
|----------|-------|
| `Framework::FastAPI => vec!["fastapi", ...]` | Analyze runtime imports |
| Create `velo.toml` | Use `pyproject.toml [tool.velo]` |
| Static framework list | User-defined config |

---

## 📋 Code Style

| Requirement | Details |
|-------------|---------|
| **Formatter** | `cargo fmt` |
| **Linter** | `cargo clippy -- -D warnings` |
| **Error Handling** | Return `Result<T, E>`, avoid `unwrap()` |
| **Logging** | Use `tracing` |

---

## ✅ Review Checklist

### TDD Compliance
- [ ] Test written before implementation
- [ ] Test fails before code, passes after
- [ ] No test-only methods in production

### Correctness
- [ ] Logic handles all cases
- [ ] Boundaries checked (min/max/zero)
- [ ] All `Option`s handled
- [ ] All `Result`s propagated

### Rust Idioms
- [ ] Ownership/borrowing correct
- [ ] Pattern matching exhaustive
- [ ] Iterators used where appropriate

---

## 🔗 Related Documents

- [AGENTS.md](../../AGENTS.md) - Top-level configuration
- [TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md) - Test isolation
- [STANDARDS.md](../STANDARDS.md) - Naming conventions

---

*This role ensures code quality through strict TDD and implementation correctness.*
