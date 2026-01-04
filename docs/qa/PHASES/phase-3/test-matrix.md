# Phase 3 Zygote Mode - QA Test Matrix

> **Related RFC**: [RFC-0002](../rfcs/0002-phase-3-zygote.md)  
> **Target Release**: v0.3.0

---

## 1. Test Environment Setup

```bash
# Build Velo with Zygote support
cargo build --release

# Ensure uv environment is set up
uv sync
```

---

## 2. Functional Tests

### 2.1 Zygote Lifecycle

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| ZYG-001 | Start Zygote daemon | `velo zygote start` | Process running, socket created | ☐ |
| ZYG-002 | Check status | `velo zygote status` | Shows PID, uptime, preloaded modules | ☐ |
| ZYG-003 | Stop Zygote | `velo zygote stop` | Clean shutdown, socket removed | ☐ |
| ZYG-004 | Auto-start | `velo run --zygote script.py` (no daemon) | Auto-starts Zygote, runs script | ☐ |
| ZYG-005 | Idle timeout | Wait 5+ minutes | Zygote auto-exits | ☐ |

### 2.2 Script Execution

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| RUN-001 | Simple script | `velo run --zygote hello.py` | Output correct | ☐ |
| RUN-002 | Script with args | `velo run --zygote app.py --port 8000` | Args passed correctly | ☐ |
| RUN-003 | Pre-loaded module | Script imports numpy | Uses cached import | ☐ |
| RUN-004 | Non-preloaded module | Script imports custom module | Loads normally | ☐ |
| RUN-005 | Exit code | Script exits with code 1 | `velo` returns code 1 | ☐ |

### 2.3 Error Handling

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| ERR-001 | Script not found | `velo run --zygote nonexistent.py` | Clear error message | ☐ |
| ERR-002 | Zygote crash | Kill Zygote process during run | Graceful error, auto-restart | ☐ |
| ERR-003 | Socket permission | Read-only socket path | Clear error, fallback | ☐ |
| ERR-004 | Import error in preload | Invalid module in config | Zygote start fails gracefully | ☐ |

---

## 3. Performance Tests

### 3.1 Startup Time ⭐

| ID | Metric | Baseline | Target | Actual | Pass/Fail |
|----|--------|----------|--------|--------|-----------|
| PERF-001 | FastAPI cold start | 540ms | < 50ms | | ☐ |
| PERF-002 | Django cold start | 400ms | < 50ms | | ☐ |
| PERF-003 | DataScience cold start | 200ms | < 30ms | | ☐ |
| PERF-004 | Fork latency | N/A | < 5ms | | ☐ |

### 3.2 Memory Usage

| ID | Metric | Target | Actual | Pass/Fail |
|----|--------|--------|--------|-----------|
| MEM-001 | Zygote process | < 300MB | | ☐ |
| MEM-002 | Per worker (COW) | < 50% of standalone | | ☐ |
| MEM-003 | 10 workers total | < 150% of 1 standalone | | ☐ |

---

## 4. Platform Compatibility

| Platform | Fork Support | Status | Notes |
|----------|--------------|--------|-------|
| macOS ARM | ✅ | ☐ | Primary dev platform |
| macOS Intel | ✅ | ☐ | Rosetta compat |
| Ubuntu 22.04 | ✅ | ☐ | CI platform |
| Windows 11 | ❌ Fallback | ☐ | Should warn + use normal mode |

---

## 5. Configuration Tests

| ID | Scenario | Steps | Expected Result | Pass/Fail |
|----|----------|-------|-----------------|-----------|
| CFG-001 | Custom preload | Set `preload = ["fastapi"]` | Only FastAPI preloaded | ☐ |
| CFG-002 | Custom timeout | Set `idle_timeout = 60` | Exits after 1 min | ☐ |
| CFG-003 | Auto-config | `velo zygote auto-config` after --profile | Updates pyproject.toml [tool.velo] | ☐ |
| CFG-004 | Invalid config | Malformed [tool.velo] section | Clear parse error | ☐ |

---

## 6. Benchmark Script

```bash
#!/bin/bash
# scripts/benchmark-zygote.sh

echo "=== Zygote Performance Benchmark ==="

# Start Zygote
velo zygote start

# Warm up
velo run --zygote bench.py > /dev/null

# Measure 10 runs
for i in {1..10}; do
    time velo run --zygote bench.py 2>&1 | grep real
done

# Cleanup
velo zygote stop
```

---

## 7. Sign-off

| Gate | Criteria | Status |
|------|----------|--------|
| Phase 3.1 | Basic fork works | ☐ |
| Phase 3.2 | Error recovery works | ☐ |
| Phase 3.3 | Auto-config works | ☐ |
| Phase 3.4 | All benchmarks pass | ☐ |

| Role | Name | Date | Signature |
|------|------|------|-----------|
| QA Lead | | | |
| Dev Lead | | | |
| Architect | | | |

---

**Document End**
