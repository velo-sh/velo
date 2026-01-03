# Velo Test Architecture Guide

> **Audience**: Dev, QA  
> **Updated**: 2026-01-02

---

## Core Principle: Environment Isolation

**Velo's development environment and user project environments MUST be completely isolated.**

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Velo Repository (.venv)     User Project (.venv)          │
│  ┌─────────────────────┐     ┌─────────────────────┐       │
│  │ pytest              │     │ fastapi             │       │
│  │ ruff                │  ≠  │ uvicorn             │       │
│  │ ... dev deps        │     │ ... user deps       │       │
│  └─────────────────────┘     └─────────────────────┘       │
│                                                             │
│         ⚠️ These must NEVER be mixed                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Test Categories

### Type 1: Velo Unit Tests

**Purpose**: Test Velo's internal Rust/Python code

**Environment**: Velo's own `.venv`

**Location**: 
- `src/**/*.rs` (Rust unit tests)
- `tests/` (Python tests that test Velo itself)

**Example**:
```bash
cargo test                    # Rust unit tests
uv run pytest tests/unit/     # Python unit tests
```

**Characteristics**:
- Uses Velo's `pyproject.toml` dependencies
- Fast execution (no project setup)
- Tests internal logic only

---

### Type 1.5: Security Verification Tests

**Purpose**: Prove internal security invariants (RFC-0008 §2.18)

**Environment**: Velo Binary + Static Analysis + Targeted E2E

**Location**:
- `tests/qa/phase*_hardening.py`
- `tests/qa/phase*_security_invariants.py`

**Key Checked Invariants**:
1. **P0-001**: Global Hash Coverage (Header + Data)
2. **P0-004**: Marshal Depth Protection (Recursion=500)
3. **P0-005**: Read Atomicity (`flock`)

---

### Type 2: User Project Integration Tests

**Purpose**: Test Velo booting actual user projects

**Environment**: **Isolated temporary project** (NOT Velo's .venv)

**Workflow**:
```
1. Create temp directory
2. Generate pyproject.toml for user project
3. Run `uv sync` to create isolated .venv
4. Run `velo run/serve` against this project
5. Verify behavior
6. Cleanup temp directory
```

**Example Implementation**:
```python
import tempfile
import subprocess
from pathlib import Path

def test_velo_boots_fastapi_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        
        # 1. Create user project structure
        (project / "pyproject.toml").write_text("""
[project]
name = "test-fastapi"
version = "0.1.0"
dependencies = ["fastapi", "uvicorn"]
""")
        
        (project / "main.py").write_text("""
from fastapi import FastAPI
app = FastAPI()
print("OK")
""")
        
        # 2. Initialize isolated environment
        subprocess.run(["uv", "sync"], cwd=project, check=True)
        
        # 3. Test Velo with isolated project
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

## Key Rules

### ✅ DO

| Rule | Reason |
|------|--------|
| Create fresh temp project for each test | Isolation |
| Use `uv sync` to init from pyproject.toml | Reproducible |
| Clean up temp directories after test | No pollution |
| Test with real dependencies (fastapi, django) | Real-world scenarios |

### ❌ DON'T

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| Import user deps in test code | Pollutes Velo's environment |
| Share .venv between tests | Non-deterministic |
| Hard-depend on global packages | Works locally, fails in CI |
| Skip `uv sync` step | Missing dependencies |

---

## Directory Structure

```
tests/
├── unit/                 # Type 1: Internal logic
├── qa/                   # Type 1.5: Security & Verification
│   ├── phase5_1/         # Zygote Async Verification
│   └── phase5_2/         # Security Invariants (P0-001+)
└── integration/          # Type 2: User projects
    └── projects/         # Sample templates
```

---

## Existing Example: benchmark_projects.py

The `benchmark_projects.py` script correctly implements isolation:

```python
# Creates isolated projects in ../velo-benchmarks/
# Each project has its own:
# - pyproject.toml
# - uv.lock
# - .venv
```

**Use this as reference for new tests.**

---

## CI Implications

In CI, each test job should:

1. Check out Velo code
2. Build Velo binary (`cargo build --release`)
3. For integration tests, create temporary isolated projects
4. Never install user project deps into Velo's environment

```yaml
# .github/workflows/ci.yml
- name: Integration Tests
  run: |
    # Build Velo
    cargo build --release
    
    # Run integration tests (they create their own isolated envs)
    uv run pytest tests/integration/ -v
```

---

**Document End**
