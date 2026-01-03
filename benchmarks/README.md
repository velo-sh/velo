# Velo Benchmark Suite

A comprehensive performance benchmarking suite for Velo's `bundle build` and Fast Loader.

## 📁 Directory Structure

```
benchmarks/
├── README.md                     # This file
├── benchmark_framework_scale.py  # Multi-level framework scaling (L1-L5)
├── benchmark_enterprise.py       # Enterprise-grade stress tests
├── benchmark_projects.py         # Project-level benchmarks
└── bench.py                      # Core benchmarking utilities
```

## 🚀 Quick Start

```bash
# Run all framework scaling benchmarks
cd benchmarks
python3 benchmark_framework_scale.py --all

# Run specific framework at specific level
python3 benchmark_framework_scale.py --fastapi --level L5

# Run enterprise benchmarks
python3 benchmark_enterprise.py --all

# Run project benchmarks
python3 benchmark_projects.py
```

## 📊 Benchmark Suites

### 1. Framework Scaling (`benchmark_framework_scale.py`)

Tests FastAPI, Flask, Django at **5 progressive scale levels**:

| Level | Description | Components |
|:---:|:---|:---:|
| L1 | Hello World | 1-5 |
| L2 | Small App | 10-20 |
| L3 | Medium App | 50-100 |
| L4 | Large App | 200-500 |
| L5 | Enterprise | 500-1000+ |

**Usage:**
```bash
python3 benchmark_framework_scale.py --all              # All frameworks, all levels
python3 benchmark_framework_scale.py --django --level L3  # Django at L3 only
python3 benchmark_framework_scale.py --all --output ci.json  # Export for CI
```

### 2. Enterprise Benchmarks (`benchmark_enterprise.py`)

Real-world stress tests simulating production monoliths:
- FastAPI: 500+ Pydantic models
- Django: 50+ apps with ORM models
- Flask: 50+ blueprints

**Usage:**
```bash
python3 benchmark_enterprise.py --fastapi
python3 benchmark_enterprise.py --django
python3 benchmark_enterprise.py --flask
python3 benchmark_enterprise.py --all
```

### 3. Project Benchmarks (`benchmark_projects.py`)

General project-level performance testing including:
- Cold start measurements
- Warm start comparisons
- CPython baseline comparisons
- Zygote mode testing

**Usage:**
```bash
python3 benchmark_projects.py
```

## 📈 Baseline Reference

See [FRAMEWORK_SCALE_BASELINES.md](../docs/qa/benchmarks/FRAMEWORK_SCALE_BASELINES.md) for established performance baselines.

### Summary (Phase 6.0):

| Framework | L5 Components | Build | Load |
|:---|:---:|:---:|:---:|
| FastAPI | 700 | 107ms | 567ms |
| Flask | 200 | 56ms | 284ms |
| Django | 100 | 54ms | 316ms |

## 🔧 CI/CD Integration

Export results to JSON for automated regression detection:

```bash
python3 benchmark_framework_scale.py --all --output benchmark_results.json
```

The JSON output includes timestamps and can be compared against baseline thresholds.

### Recommended Thresholds:

| Level | Max Build | Max Load |
|:---:|:---:|:---:|
| L1-L2 | 50ms | 500ms |
| L3 | 75ms | 600ms |
| L4 | 100ms | 700ms |
| L5 | 150ms | 800ms |

---

**Velo QA Working Group** | Phase 6.0
