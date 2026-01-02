# RFC-0007: Continuous Benchmarking Infrastructure

> **Status**: `Draft`  
> **Author**: Architect  
> **Created**: 2026-01-03  
> **Target Release**: Velo v0.5.0  
> **Branch**: `phase-5.0/fast-loader`

---

## 1. Executive Summary

### 1.1 Problem

Performance regressions are difficult to detect without systematic tracking:
- No historical baseline for comparison
- Manual benchmarking is inconsistent
- Regressions discovered late in development cycle

### 1.2 Goal

**Automated performance tracking** with:
- CI-integrated benchmarks on every commit
- Historical trend visualization
- Automatic regression alerts

---

## 2. Technical Design

### 2.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     CI Pipeline (GitHub Actions)             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Push/PR          Benchmark           Compare               │
│   ┌─────────┐     ┌─────────┐        ┌─────────┐           │
│   │ Trigger │────▶│ criterion│───────▶│ Baseline│           │
│   │         │     │ benches │        │ Check   │           │
│   └─────────┘     └─────────┘        └─────────┘           │
│                        │                   │                │
│                        ▼                   ▼                │
│                  ┌─────────┐        ┌─────────┐            │
│                  │ JSON    │        │ Alert   │            │
│                  │ Output  │        │ on Fail │            │
│                  └────┬────┘        └─────────┘            │
│                       │                                     │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  gh-pages Branch                             │
├─────────────────────────────────────────────────────────────┤
│   /dev/bench/                                                │
│   ├── data.js         (Historical benchmark data)           │
│   ├── index.html      (Dashboard)                           │
│   └── chart.min.js    (Visualization library)               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Toolchain Selection

| Tool | Purpose | Rationale |
|------|---------|-----------|
| **criterion.rs** | Rust benchmarking | Statistical rigor, warm-up, outlier detection |
| **github-action-benchmark** | CI integration | Free, native GitHub, auto-visualization |
| **Chart.js** | Visualization | Lightweight, interactive charts |

### 2.3 Benchmark Categories

| Category | Metrics | Target |
|----------|---------|--------|
| **Bundle I/O** | Load time, Build time | < 100ms / 4MB |
| **Hash Performance** | BLAKE3 throughput | > 3 GB/s |
| **Import Hook** | Module lookup | < 1μs |
| **E2E Cold Start** | FastAPI startup | < 200ms |

---

## 3. Implementation

### 3.1 Benchmark Suite

```rust
// benches/fast_loader.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};

/// Bundle Loading Benchmarks
fn bench_bundle_load(c: &mut Criterion) {
    let mut group = c.benchmark_group("bundle_load");
    
    for size in [1, 4, 16, 64].iter() {
        group.bench_with_input(
            BenchmarkId::new("cold", size),
            size,
            |b, &size| {
                let path = format!("fixtures/bundle_{}mb.veloc", size);
                b.iter(|| load_bundle(black_box(&path)))
            },
        );
    }
    group.finish();
}

/// BLAKE3 Hash Benchmarks
fn bench_blake3(c: &mut Criterion) {
    let data_4mb = vec![0u8; 4 * 1024 * 1024];
    
    c.bench_function("blake3_4mb", |b| {
        b.iter(|| blake3::hash(black_box(&data_4mb)))
    });
}

/// Module Lookup Benchmarks
fn bench_module_lookup(c: &mut Criterion) {
    let bundle = load_test_bundle();
    let modules = ["json", "numpy.core", "fastapi.applications"];
    
    let mut group = c.benchmark_group("module_lookup");
    for module in modules {
        group.bench_function(module, |b| {
            b.iter(|| bundle.get_module(black_box(module)))
        });
    }
    group.finish();
}

criterion_group!(benches, bench_bundle_load, bench_blake3, bench_module_lookup);
criterion_main!(benches);
```

### 3.2 GitHub Actions Workflow

```yaml
# .github/workflows/benchmark.yml
name: Continuous Benchmarking

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: write
  deployments: write

jobs:
  benchmark:
    name: Performance Regression Check
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Rust
        uses: dtolnay/rust-action@stable
      
      - name: Run Benchmarks
        run: |
          cargo bench --bench fast_loader -- --output-format bencher \
            | tee benchmark-results.txt
      
      - name: Store Benchmark Results
        uses: benchmark-action/github-action-benchmark@v1
        with:
          name: Velo Fast Loader Benchmark
          tool: 'cargo'
          output-file-path: benchmark-results.txt
          github-token: ${{ secrets.GITHUB_TOKEN }}
          
          # Regression detection
          alert-threshold: '120%'
          fail-on-alert: true
          comment-on-alert: true
          
          # Historical data
          auto-push: ${{ github.ref == 'refs/heads/main' }}
          gh-pages-branch: gh-pages
          benchmark-data-dir-path: dev/bench
```

### 3.3 Regression Thresholds

| Metric | Warning | Failure |
|--------|---------|---------|
| Bundle load time | +10% | +20% |
| BLAKE3 throughput | -10% | -20% |
| Module lookup | +20% | +50% |
| Memory usage | +10% | +20% |

### 3.4 Dashboard Features

```
┌─────────────────────────────────────────────────────────────┐
│  Velo Performance Dashboard                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📈 Bundle Load Time (ms)                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │    ╭──╮                                              │   │
│  │   ╱    ╲    ╭──────────────────────────────────      │   │
│  │  ╱      ╲──╯                                         │   │
│  │ ╱                                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│    Jan 1    Jan 5     Jan 10    Jan 15    Jan 20           │
│                                                              │
│  📊 Current vs Baseline                                      │
│  ┌────────────────┬────────────┬────────────┬──────────┐   │
│  │ Metric         │ Current    │ Baseline   │ Change   │   │
│  ├────────────────┼────────────┼────────────┼──────────┤   │
│  │ bundle_load    │ 42.3ms     │ 40.1ms     │ +5.5% ⚠️ │   │
│  │ blake3_4mb     │ 1.2ms      │ 1.2ms      │ +0.0% ✅ │   │
│  │ module_lookup  │ 0.8μs      │ 0.9μs      │ -11% 🎉  │   │
│  └────────────────┴────────────┴────────────┴──────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

- [ ] Create `benches/fast_loader.rs` with criterion
- [ ] Add benchmark fixtures (1MB, 4MB, 16MB bundles)
- [ ] Configure `.github/workflows/benchmark.yml`
- [ ] Test on feature branch

### Phase 2: Dashboard (Week 2)

- [ ] Enable gh-pages branch
- [ ] Verify historical data accumulation
- [ ] Add link to README
- [ ] Document benchmark methodology

### Phase 3: Integration (Week 2)

- [ ] Add benchmark badge to README
- [ ] Configure PR comments for regression alerts
- [ ] Document threshold tuning process

---

## 5. Acceptance Criteria

| Test | Description | Pass Criteria |
|------|-------------|---------------|
| CI-001 | Benchmark runs on push | Job completes successfully |
| CI-002 | Regression detection | Fails on > 120% degradation |
| CI-003 | Historical storage | Data persists to gh-pages |
| VIS-001 | Dashboard accessible | Charts render correctly |
| VIS-002 | Commit correlation | Each point links to commit |

---

## 6. Success Metrics

| Metric | Target |
|--------|--------|
| Benchmark stability | < 5% variance between runs |
| Dashboard uptime | 99.9% |
| Regression detection latency | < 10 minutes |
| Historical data retention | 6 months |

---

## 7. Future Enhancements

- **Phase 2**: Memory profiling (heaptrack integration)
- **Phase 3**: Flamegraph generation in CI
- **Phase 4**: Multi-platform benchmarks (Linux/macOS/Windows)
- **Phase 5**: Custom Grafana dashboard for production monitoring

---

**Document End**
