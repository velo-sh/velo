# Velo Benchmark User Guide

> A step-by-step guide to running Velo performance benchmarks

## Table of Contents

1. [Prerequisites](#-prerequisites)
2. [Quick Start (5 minutes)](#-quick-start-5-minutes)
3. [Testing Individual Frameworks](#-testing-individual-frameworks)
4. [CI/CD Integration](#%EF%B8%8F-cicd-integration)
5. [Understanding Results](#-understanding-results)
6. [FAQ](#-faq)

---

## ✅ Prerequisites

### 1. Ensure Velo is Compiled

```bash
# In velo_qa root directory
cargo build --release

# Verify successful build
./target/release/velo --version
```

### 2. Ensure Python Environment

```bash
# Recommended: use uv
uv sync

# Or ensure Python 3.11+ is installed
python3 --version
```

---

## 🚀 Quick Start (5 minutes)

### Step 1: Navigate to benchmarks directory

```bash
cd benchmarks
```

### Step 2: Run Hello World level tests

```bash
python3 benchmark_framework_scale.py --all --level L1
```

### Step 3: View results

Example output:
```
==========================================================================================
🎯 FRAMEWORK SCALING BENCHMARK RESULTS
==========================================================================================
Framework    Level Scale           Components   Build (ms)    Load (ms) Status  
------------------------------------------------------------------------------------------
fastapi      L1    Hello World              2         35.1        390.9 ✅ PASS  
flask        L1    Hello World              1         22.2        197.6 ✅ PASS  
django       L1    Hello World              1         22.3        271.6 ✅ PASS  
==========================================================================================
```

### Step 4: Run full test suite (all levels)

```bash
python3 benchmark_framework_scale.py --all
```

⏱️ Estimated time: ~3-5 minutes

---

## 🎯 Testing Individual Frameworks

### FastAPI

```bash
# FastAPI only, all levels
python3 benchmark_framework_scale.py --fastapi

# FastAPI L5 Enterprise (700 components)
python3 benchmark_framework_scale.py --fastapi --level L5
```

### Flask

```bash
# Flask only, all levels
python3 benchmark_framework_scale.py --flask

# Flask L3 Medium project (50 components)
python3 benchmark_framework_scale.py --flask --level L3
```

### Django

```bash
# Django only, all levels
python3 benchmark_framework_scale.py --django

# Django L4 Large project (50 apps)
python3 benchmark_framework_scale.py --django --level L4
```

---

## 🏗️ Enterprise Stress Tests

For realistic production environment simulation:

```bash
# Run enterprise benchmarks
python3 benchmark_enterprise.py --all

# FastAPI Enterprise only (500+ Pydantic models)
python3 benchmark_enterprise.py --fastapi
```

---

## ⚙️ CI/CD Integration

### Step 1: Export JSON results

```bash
python3 benchmark_framework_scale.py --all --output ci_results.json
```

### Step 2: Check thresholds in CI script

```bash
# Example: Check if L5 build time exceeds 150ms
python3 -c "
import json
with open('ci_results.json') as f:
    data = json.load(f)
for r in data['results']:
    if r['level'] == 'L5' and r['build_time_ms'] > 150:
        print(f\"REGRESSION: {r['framework']} build {r['build_time_ms']}ms > 150ms\")
        exit(1)
print('All benchmarks within threshold!')
"
```

### Step 3: GitHub Actions example

```yaml
- name: Run Performance Benchmarks
  run: |
    cd benchmarks
    python3 benchmark_framework_scale.py --all --output results.json

- name: Check for Regressions
  run: |
    python3 scripts/check_benchmark_thresholds.py results.json
```

---

## 📊 Understanding Results

### Metrics Explained

| Metric | Description | Target |
|:---|:---|:---|
| **Build (ms)** | `velo bundle build` duration | L5 < 150ms |
| **Load (ms)** | `velo run --fast` startup time | L5 < 800ms |
| **Components** | Number of generated components | - |

### Scale Levels Explained

| Level | Scenario | Typical Scale |
|:---:|:---|:---|
| L1 | Hello World | 1-5 components |
| L2 | Small project | 10-20 components |
| L3 | Medium project | 50-100 components |
| L4 | Large project | 200-500 components |
| L5 | Enterprise | 500-1000+ components |

### Baseline Reference

```
FastAPI L5 (700 components): Build ~107ms, Load ~567ms
Flask   L5 (200 components): Build ~56ms,  Load ~284ms
Django  L5 (100 apps):       Build ~54ms,  Load ~316ms
```

---

## ❓ FAQ

### Q: Test fails with "Velo binary not found"

**A:** Ensure Release build is compiled:
```bash
cd ..  # Return to velo_qa root
cargo build --release
cd benchmarks
```

### Q: FastAPI test reports "pydantic not found"

**A:** The script auto-installs dependencies, but if it fails, install manually:
```bash
uv add fastapi pydantic flask django
```

### Q: Tests are too slow

**A:** Test specific levels only:
```bash
# Test only L1 and L2
python3 benchmark_framework_scale.py --all --level L1
python3 benchmark_framework_scale.py --all --level L2
```

### Q: How to compare two test runs

**A:** Export JSON and diff:
```bash
# First run
python3 benchmark_framework_scale.py --all --output before.json

# After code changes
python3 benchmark_framework_scale.py --all --output after.json

# Compare (manual or scripted)
diff before.json after.json
```

---

## 📎 Related Links

- [Performance Baselines](../docs/qa/benchmarks/FRAMEWORK_SCALE_BASELINES.md)
- [Benchmarks README](./README.md)
- [QA Testing Guide](../docs/qa/tiered-testing-guide.md)

---

**Velo QA Working Group** | Phase 6.0
