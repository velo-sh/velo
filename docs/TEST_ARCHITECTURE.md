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

**Location**: `src/**/*.rs` (Rust unit tests)

**Example**:
```bash
cargo test                    # Rust unit tests
```

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

**Example**:
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

### ❌ DON'T

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| Import user deps in test code | Pollutes Velo's environment |
| Share .venv between tests | Non-deterministic |
| Skip `uv sync` step | Missing dependencies |

---

**Document End**
