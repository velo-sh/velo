# Framework Scaling Benchmark Baselines

**Date**: 2026-01-03
**Velo Version**: Phase 6.0 Static Graph (`34e33ab`)
**Hardware**: M-Series Mac (10 cores)

## 📊 Complete Baseline Results

### FastAPI (Pydantic Models + API Routers)

| Level | Scale | Components | Build (ms) | Load (ms) |
|:---:|:---|:---:|:---:|:---:|
| L1 | Hello World | 2 | **35.1** | **390.9** |
| L2 | Small App | 20 | **30.1** | **382.0** |
| L3 | Medium App | 100 | **41.5** | **416.4** |
| L4 | Large App | 300 | **56.7** | **459.6** |
| L5 | Enterprise | 700 | **106.7** | **566.5** |

### Flask (Blueprints)

| Level | Scale | Components | Build (ms) | Load (ms) |
|:---:|:---|:---:|:---:|:---:|
| L1 | Hello World | 1 | **22.2** | **197.6** |
| L2 | Small App | 10 | **24.4** | **227.3** |
| L3 | Medium App | 50 | **35.0** | **222.4** |
| L4 | Large App | 100 | **40.8** | **244.7** |
| L5 | Enterprise | 200 | **56.3** | **284.4** |

### Django (Apps + Models)

| Level | Scale | Components | Build (ms) | Load (ms) |
|:---:|:---|:---:|:---:|:---:|
| L1 | Hello World | 1 | **22.3** | **271.6** |
| L2 | Small App | 5 | **33.4** | **298.8** |
| L3 | Medium App | 20 | **28.6** | **286.7** |
| L4 | Large App | 50 | **38.0** | **321.1** |
| L5 | Enterprise | 100 | **53.9** | **315.8** |

---

## 🎯 Key Observations

1. **Excellent Scaling**: Build time increases sub-linearly with component count
2. **Flask Fastest**: Flask consistently has the lowest load times (~200-300ms)
3. **FastAPI Heaviest**: Pydantic models add overhead but still sub-second
4. **Django Stable**: Load times remain consistent across scales (~280-320ms)

## 📈 Regression Thresholds

For CI/CD gating, we recommend these thresholds:

| Level | Max Build | Max Load |
|:---:|:---:|:---:|
| L1-L2 | 50ms | 500ms |
| L3 | 75ms | 600ms |
| L4 | 100ms | 700ms |
| L5 | 150ms | 800ms |

---

## Usage

```bash
# Run all frameworks at all levels
python3 benchmark_framework_scale.py --all

# Run specific framework at specific level
python3 benchmark_framework_scale.py --fastapi --level L3

# Export results to JSON
python3 benchmark_framework_scale.py --all --output results.json
```

---
**QA Working Group** | Velo Performance Baseline v1.0
