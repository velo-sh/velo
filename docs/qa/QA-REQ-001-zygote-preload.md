# QA Test Requirement: Zygote Preload Performance

**QA-REQ-001**: Zygote Preload Verification

## Background

Testing confirmed that Zygote with preload reduces FastAPI startup from 470ms to 275ms (55% faster).

## Test Requirements

### PERF-PRELOAD-001: Manual Preload Performance

**Precondition**: 
- `bench_fastapi` project with dependencies installed
- `velo_zygote` symlinked in project directory

**Steps**:
```bash
cd ../velo-benchmarks/bench_fastapi
velo zygote stop
velo zygote start --preload fastapi,pydantic,uvicorn,starlette,numpy,pandas
time velo run --zygote bench.py
```

**Expected**: `< 300ms` (vs 470ms without preload)

---

### PERF-PRELOAD-002: pyproject.toml Preload (After DEV-FIX-001)

**Precondition**: DEV-FIX-001 implemented

**Steps**:
```bash
cd ../velo-benchmarks/bench_fastapi
# Ensure pyproject.toml has [tool.velo] preload = [...]
velo zygote stop
velo run --zygote bench.py  # Should auto-start with preload
time velo run --zygote bench.py
```

**Expected**: `< 300ms`

---

### REG-001: No Preload Baseline

**Steps**:
```bash
velo zygote stop
velo zygote start  # No --preload
time velo run --zygote bench.py
```

**Expected**: `~450-500ms` (baseline without preload)
