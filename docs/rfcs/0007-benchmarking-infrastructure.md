# RFC-0007: Performance Tracking Infrastructure

> **Status**: `Draft`  
> **Author**: Architect  
> **Created**: 2026-01-03  
> **Target Release**: Velo v0.5.0  
> **Branch**: `phase-5.0/fast-loader`

---

## 1. Executive Summary

### 1.1 Problem

Performance optimization requires reliable historical tracking:
- CI environments are inconsistent (noisy data)
- No way to compare before/after optimization
- Manual benchmarking results get lost

### 1.2 Goal

**Local-first performance tracking** with:
- Consistent environment (developer's machine)
- Historical data stored in repository
- Easy before/after comparison

> [!IMPORTANT]
> **Design Principle**: Local benchmark as **primary source**, CI as **reference only**.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCAL (Primary)                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Developer      Benchmark       History         Compare     │
│   ┌─────────┐   ┌─────────┐   ┌─────────┐    ┌─────────┐   │
│   │ velo    │──▶│ criterion│──▶│ .velo/  │───▶│ velo    │   │
│   │ bench   │   │         │   │ bench/  │    │ compare │   │
│   └─────────┘   └─────────┘   └─────────┘    └─────────┘   │
│                                    │                        │
│                                    ▼                        │
│                              ┌─────────┐                    │
│                              │ history │                    │
│                              │ .jsonl  │                    │
│                              └─────────┘                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    CI (Reference Only)                       │
├─────────────────────────────────────────────────────────────┤
│   • Detect large regressions (>20%)                          │
│   • Not for precise optimization comparison                  │
│   • Data stored on gh-pages (visualization)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Local Benchmark System

### 3.1 CLI Commands

```bash
# Run benchmark and save to history
velo bench --save

# Run without saving (quick check)
velo bench

# Compare current with specific commit
velo bench compare <commit>

# Compare two commits
velo bench compare <commit1> <commit2>

# View historical trend
velo bench history [--last N]

# Export HTML report
velo bench report --output perf_report.html
```

### 3.2 Data Storage

**Location**: `.velo/bench/history.jsonl`

```jsonl
{"commit":"abc123","date":"2026-01-03T01:00:00Z","machine":"mbp-m2-16gb","bench":"bundle_load_4mb","value_ns":42300000}
{"commit":"abc123","date":"2026-01-03T01:00:00Z","machine":"mbp-m2-16gb","bench":"blake3_4mb","value_ns":1200000}
{"commit":"def456","date":"2026-01-04T10:00:00Z","machine":"mbp-m2-16gb","bench":"bundle_load_4mb","value_ns":38500000}
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `commit` | string | Git commit hash (short) |
| `date` | ISO8601 | Timestamp |
| `machine` | string | Machine identifier |
| `bench` | string | Benchmark name |
| `value_ns` | u64 | Duration in nanoseconds |

### 3.3 Machine Identifier

```rust
fn get_machine_id() -> String {
    // Format: {hostname}-{cpu}-{mem}
    // Example: "mbp-m2-16gb", "linux-i9-32gb"
    format!("{}-{}-{}gb", 
        hostname::get().unwrap_or("unknown"),
        cpu_model_short(),
        total_memory_gb()
    )
}
```

### 3.4 Output Examples

**`velo bench --save`**:
```
Running benchmarks...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  bundle_load_4mb     42.3ms   (± 1.2ms)
  blake3_4mb           1.2ms   (± 0.1ms)
  module_lookup        0.8μs   (± 0.02μs)

✅ Results saved to .velo/bench/history.jsonl
   Commit: abc123 | Machine: mbp-m2-16gb
```

**`velo bench compare abc123`**:
```
Comparing: def456 (current) vs abc123 (baseline)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Benchmark          Current     Baseline    Change
  ─────────────────────────────────────────────────────
  bundle_load_4mb    38.5ms      42.3ms      -9.0% 🎉
  blake3_4mb          1.2ms       1.2ms      +0.0% ✅
  module_lookup       0.8μs       0.9μs     -11.1% 🎉

Summary: 2 improved, 1 unchanged, 0 regressed
```

**`velo bench history --last 5`**:
```
History: bundle_load_4mb (last 5 runs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Commit    Date         Value      Change
  ─────────────────────────────────────────────────────
  def456    Jan 4        38.5ms     -9.0% 🎉
  abc123    Jan 3        42.3ms     +2.1% 
  789xyz    Jan 2        41.4ms     -5.2% 🎉
  456uvw    Jan 1        43.7ms     baseline
```

---

## 4. Benchmark Suite (criterion.rs)

```rust
// benches/fast_loader.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};

fn bench_bundle_load(c: &mut Criterion) {
    let mut group = c.benchmark_group("bundle_load");
    
    for size in [1, 4, 16].iter() {
        group.bench_with_input(
            BenchmarkId::new("cold", format!("{}mb", size)),
            size,
            |b, &size| {
                let path = format!("fixtures/bundle_{}mb.veloc", size);
                b.iter(|| load_bundle(black_box(&path)))
            },
        );
    }
    group.finish();
}

fn bench_blake3(c: &mut Criterion) {
    let data = vec![0u8; 4 * 1024 * 1024];
    c.bench_function("blake3_4mb", |b| {
        b.iter(|| blake3::hash(black_box(&data)))
    });
}

fn bench_module_lookup(c: &mut Criterion) {
    let bundle = load_test_bundle();
    c.bench_function("module_lookup", |b| {
        b.iter(|| bundle.get_module(black_box("numpy.core")))
    });
}

criterion_group!(benches, bench_bundle_load, bench_blake3, bench_module_lookup);
criterion_main!(benches);
```

---

## 5. CI Integration (Reference Only)

> [!WARNING]
> CI benchmarks are for **coarse regression detection** only.
> Do NOT use CI results for precise optimization comparison.

### 5.1 Purpose

| Use Case | Suitable? |
|----------|-----------|
| Detect >20% regression | ✅ Yes |
| Compare 5% optimization | ❌ No (too noisy) |
| Historical visualization | ✅ Yes (approximate) |

### 5.2 GitHub Actions (Optional)

```yaml
# .github/workflows/benchmark.yml
name: Benchmark (Reference)

on:
  push:
    branches: [main]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cargo bench -- --output-format bencher | tee results.txt
      
      - uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'cargo'
          output-file-path: results.txt
          alert-threshold: '150%'  # Very lenient (CI noise)
          fail-on-alert: false     # Don't block PR
          comment-on-alert: true   # Just notify
```

---

## 6. Implementation Plan

### Phase 1: Core (Week 1)

- [ ] Create `benches/fast_loader.rs`
- [ ] Implement `velo bench` command
- [ ] Implement `velo bench --save` (JSONL output)
- [ ] Implement `velo bench compare`

### Phase 2: Polish (Week 2)

- [ ] Implement `velo bench history`
- [ ] Implement `velo bench report` (HTML)
- [ ] Add benchmark fixtures
- [ ] Documentation

### Phase 3: CI (Optional, Week 3)

- [ ] Add `.github/workflows/benchmark.yml`
- [ ] Enable gh-pages visualization
- [ ] Add README badge

---

## 7. Acceptance Criteria

| Test | Description | Pass Criteria |
|------|-------------|---------------|
| LOCAL-001 | `velo bench` runs | Outputs metrics |
| LOCAL-002 | `velo bench --save` | Creates JSONL entry |
| LOCAL-003 | `velo bench compare` | Shows diff correctly |
| LOCAL-004 | Same machine consistency | < 5% variance |

---

## 8. Best Practices

### 8.1 When to Benchmark

```bash
# Before optimization
git checkout main
velo bench --save

# After optimization
git checkout feature-branch
velo bench --save

# Compare
velo bench compare main
```

### 8.2 Machine Consistency

> [!CAUTION]
> Only compare benchmarks from the **same machine**.

- Close other applications
- Use consistent power settings
- Run multiple times (criterion handles this)

---

**Document End**
