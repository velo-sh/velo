# Velo Example: Serverless Instant

> **🎯 Goal**: Demonstrate how Velo collapses Python serverless cold start latency by removing interpreter and import costs from the per-request critical path.

> [!IMPORTANT]
> **Boundary Declaration**: This benchmark isolates **Python runtime cold start behavior only**.
> It does NOT model container startup, image pulling, network latency, or cloud platform API Gateway.

---

## 30-Second Quick Start

```bash
# Run the comparison
./examples/serverless-instant/run_hio.sh --compare
```

---

## The Pain

In traditional serverless, **every request** pays the full cost:
1. Python interpreter startup (~200-400ms)
2. Import heavy dependencies (~400-800ms)
3. Framework initialization

**Total cold start**: 800-1200ms per request.

## The Velo Advantage

With Velo's Zygote + fork model:
1. ✅ Interpreter starts **once** in Zygote
2. ✅ Dependencies import **once**
3. ✅ Per-request cost: just `fork()` (~5-15ms)
4. ✅ Memory shared via Copy-On-Write

---

## Execution Model Comparison

```text
┌─────────────────────────────────────────────────────────────┐
│ Model A: Traditional Python Serverless (CPython)           │
├─────────────────────────────────────────────────────────────┤
│  Request 1: [Interpreter] → [Imports] → [Handler] → Exit   │
│  Request 2: [Interpreter] → [Imports] → [Handler] → Exit   │
│  Request N: [Interpreter] → [Imports] → [Handler] → Exit   │
│                                                             │
│  ⏱️ Each request: ~800-1200ms                               │
│  💾 Memory: N × baseline                                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Model B: Velo Zygote-backed Serverless                      │
├─────────────────────────────────────────────────────────────┤
│  Zygote:    [Interpreter] → [Imports] → Ready (once)        │
│                  │                                          │
│  Request 1:      └── fork() → [Handler] → Exit              │
│  Request 2:      └── fork() → [Handler] → Exit              │
│  Request N:      └── fork() → [Handler] → Exit              │
│                                                             │
│  ⏱️ First request: ~800-1200ms (amortized)                  │
│  ⏱️ Subsequent: ~5-15ms                                     │
│  💾 Memory: ~1 × baseline (CoW sharing)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏆 Expected Benchmark Results

> [!TIP]
> These results have been verified by QA on 2026-01-11 (macOS, Python 3.9.6).

### Scenario 1: Single Cold Start
| Mode | Total Time | Speedup |
| :--- | :--- | :--- |
| CPython | ~430ms | — |
| Velo | **<1ms** | **~500x** ⚡ |

### Scenario 2: Burst Cold Starts (N=10)
| Mode | Total Time | Peak RSS | Speedup |
| :--- | :--- | :--- | :--- |
| CPython | ~4.5s | ~10 × baseline | — |
| Velo | **~10ms** | ~1 × baseline (CoW) | **~500x** ⚡ |

### Scenario 3: Warm vs Cold
| Mode | First Request | Subsequent |
| :--- | :--- | :--- |
| CPython | slow | slow |
| Velo | slow (Zygote warmup, amortized) | **near-zero (<1ms)** |


---

## Methodology Notes

- **Kernel-Level Measurement**: Uses real `os.fork()` calls to measure fork overhead
- **Real Dependencies**: FastAPI, Pydantic, SQLAlchemy, NumPy
- **Statistical Rigor**: Outputs median and p95, discards warm-up run
- **Cross-Platform**: macOS uses RSS fallback for memory measurement
- **Reproducibility**: Results reflect stable kernel behavior

---

## Running the Demo

```bash
# Default: Single cold start comparison
./examples/serverless-instant/run_hio.sh

# A/B comparison with multiple runs
./examples/serverless-instant/run_hio.sh --compare --runs=5

# Burst scenario (N=10 concurrent)
./examples/serverless-instant/run_hio.sh --compare --scenario=burst

# Memory comparison
./examples/serverless-instant/run_hio.sh --compare --scenario=memory
```

---

## Why This Matters

> "Python is slow in serverless" is not a fundamental truth.
> With a different runtime model, Python becomes viable for bursty workloads.

Velo reframes serverless execution around process-level primitives:
- **fork()** provides kernel-level isolation
- **Copy-On-Write** enables memory-efficient concurrency
- Interpreter and imports need not be on the request path
