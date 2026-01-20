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
> These results have been verified by QA on 2026-01-12 (macOS, Python 3.9.6).

### Scenario 1: Single Cold Start
| Mode | Total Time (Median) | P95 | Speedup |
| :--- | :--- | :--- | :--- |
| CPython | ~450ms | ~588ms | — |
| Velo | **<1ms** | ~1.2ms | **~470x** ⚡ |

### Scenario 2: Burst Cold Starts (N=10)
| Mode | Total Time (Median) | P95 | Speedup |
| :--- | :--- | :--- | :--- |
| CPython | ~436ms | ~516ms | — |
| Velo | **~1.1ms** | ~1.3ms | **~406x** ⚡ |

### Scenario 3: Warm vs Cold
| Mode | First Request | Subsequent |
| :--- | :--- | :--- |
| CPython | slow | slow |
| Velo | slow (Zygote warmup, amortized) | **near-zero (<1ms)** |

### Memory Efficiency
| Metric | CPython (N=10) | Velo (N=10) | Improvement |
| :--- | :--- | :--- | :--- |
| **Peak RSS** | ~660MB | **~66MB** | **~90% saved** 📉 |
| **Per-Worker Delta** | ~66MB | **~0MB** (CoW) | **Shared** |

> **Note**: CPython spawns N independent processes, each loading the full runtime (~66MB). Velo's fork() shares memory via Copy-On-Write — workers only allocate memory for modified pages.

### Time to First Byte (TTFB)
| Mode | TTFB (Cold) | TTFB (Warm) | API Gateway Ready |
| :--- | :--- | :--- | :--- |
| CPython | ~450ms | ~450ms (same) | ❌ High latency |
| Velo | **<1ms** | **<1ms** | ✅ Sub-millisecond |

> **Why TTFB Matters**: In serverless, TTFB directly impacts user experience and API Gateway timeout budgets. Traditional Python cold starts (~450ms) consume 45% of a typical 1-second timeout, leaving minimal headroom for business logic. Velo's sub-millisecond TTFB preserves the full timeout budget for actual work.

---

## Methodology Notes

- **Kernel-Level Measurement**: Uses real `os.fork()` calls to measure fork overhead
- **Real Dependencies**: FastAPI, Pydantic, SQLAlchemy, NumPy
- **Statistical Rigor**: Outputs median and p95, discards warm-up run
- **Cross-Platform**: macOS uses RSS fallback for memory measurement
- **Reproducibility**: Results reflect stable kernel behavior

---

## Running the Demo

### Prerequisites

Install [uv](https://github.com/astral-sh/uv) package manager:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via Homebrew (macOS)
brew install uv
```

### Run the Benchmark

```bash
# Quick start (uv handles dependencies automatically)
./examples/serverless-instant/run_hio.sh --compare --runs=20

# Or run directly with uv
uv run python examples/serverless-instant/benchmark.py --runs=20
```

---

## Why This Matters

> "Python is slow in serverless" is not a fundamental truth.
> With a different runtime model, Python becomes viable for bursty workloads.

Velo reframes serverless execution around process-level primitives:
- **fork()** provides kernel-level isolation
- **Copy-On-Write** enables memory-efficient concurrency
- Interpreter and imports need not be on the request path
