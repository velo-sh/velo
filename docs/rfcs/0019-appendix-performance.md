# RFC-0019 Appendix: Performance Benefits Assessment

> **Parent RFC**: [RFC-0019 Native Sovereignty](./0019-native-sovereignty.md)
> **Status**: DRAFT
> **Last Updated**: 2026-01-12

## Executive Summary

This document provides a detailed performance benefits assessment for the technologies documented in RFC-0019's Technology Radar. It serves as a reference for QA validation and stakeholder communication.

---

## 1. Phase-by-Phase Benefits Projection

### 1.1 Phase 7.2 (Immediate Benefits)

| Technology | Benefit Type | Expected Improvement | Confidence |
|:---|:---|:---|:---|
| **Granian Core (Rust)** | Latency | -30% HTTP parsing overhead | ⭐⭐⭐ High |
| **uvloop (default)** | Latency | -15% Python async overhead | ⭐⭐⭐ High |
| **jemalloc** | Memory | -20% fragmentation, more stable | ⭐⭐⭐ High |
| **LTO + codegen=1** | Throughput | +10-15% overall performance | ⭐⭐⭐ High |
| **Buffer Pool** | Latency | -5% allocation overhead | ⭐⭐ Medium |
| **Zygote Fork** | Cold Start | -90% startup time | ⭐⭐⭐ High |

**Phase 7.2 Aggregate Estimate**: 30-50% overall improvement

### 1.2 Phase 8.x (Long-term Benefits)

| Technology | Benefit Type | Expected Improvement | Confidence |
|:---|:---|:---|:---|
| **io_uring** | Throughput | +20-40% syscall efficiency | ⭐⭐ Medium |
| **Sonic-rs** | Throughput | +50% JSON serialization | ⭐⭐⭐ High |
| **Monoio/Glommio** | Latency | -20% scheduling overhead | ⭐⭐ Medium |
| **Ring Buffer** | Throughput | +10% lock-free transfer | ⭐⭐ Medium |
| **Memory Arena** | Latency | -10% alloc/dealloc | ⭐⭐ Medium |
| **mimalloc** | Latency | -5% hot path allocation | ⭐⭐ Medium |

**Phase 8.x Aggregate Estimate**: 20-40% additional improvement (cumulative: 50-90%)

### 1.3 Phase 9.x (Future Benefits)

| Technology | Benefit Type | Expected Improvement | Confidence |
|:---|:---|:---|:---|
| **HTTP/3 (QUIC)** | Latency | -20% connection establishment | ⭐ Low |
| **Python Free-Threading** | Throughput | 2-4x multi-core utilization | ⭐ Low |
| **Zero-copy mmap** | Memory | -50% large body overhead | ⭐ Low |

---

## 2. Baseline vs Target Comparison

| Metric | Uvicorn Baseline | Phase 7.2 Target | Phase 8.x Target |
|:---|:---|:---|:---|
| **Latency (P99)** | ~5ms | **<3.5ms** (-30%) | **<2ms** (-60%) |
| **Throughput (RPS)** | 10K | **12-15K** (1.2-1.5x) | **20K+** (2x) |
| **Memory per Worker** | 50MB | **35MB** (-30%) | **25MB** (-50%) |
| **Cold Start** | 500-800ms | **<50ms** (-90%) | **<20ms** (-95%) |

---

## 3. Competitive Analysis

| Metric | Uvicorn | Gunicorn | Velo 7.2 | Velo 8.x |
|:---|:---|:---|:---|:---|
| **RPS (single core)** | 3K | 2K | **4K** | **5K+** |
| **P99 Latency** | 5ms | 8ms | **3.5ms** | **<2ms** |
| **Cold Start** | 500ms | 800ms | **50ms** | **20ms** |
| **Memory/Worker** | 50MB | 80MB | **35MB** | **25MB** |

---

## 4. QA Validation Requirements

> [!IMPORTANT]
> The following tests MUST be executed to validate performance claims.

### 4.1 Phase 7.2 Validation Suite

| Test ID | Test Name | Target Metric | Pass Criteria |
|:---|:---|:---|:---|
| **PERF-72-001** | Latency Baseline | P99 Latency | < 3.5ms |
| **PERF-72-002** | Throughput Baseline | RPS @ 50% CPU | > 12K RPS |
| **PERF-72-003** | Memory Efficiency | RSS per Worker | < 40MB |
| **PERF-72-004** | Cold Start Time | First request | < 100ms |
| **PERF-72-005** | uvloop Detection | Event Loop Type | uvloop active |
| **PERF-72-006** | jemalloc Verification | Allocator Check | jemalloc loaded |

### 4.2 Stress Testing Requirements

| Test ID | Test Name | Duration | Conditions |
|:---|:---|:---|:---|
| **STRESS-001** | Sustained Load | 1 hour | 10K QPS constant |
| **STRESS-002** | Memory Stability | 4 hours | Verify no leaks |
| **STRESS-003** | Spike Handling | 10 mins | 0 → 20K → 0 RPS |
| **STRESS-004** | GIL Contention | 30 mins | 8 workers, CPU-bound |

### 4.3 Regression Prevention

| Check | Method | Frequency |
|:---|:---|:---|
| **P99 Regression** | CI benchmark | Every PR |
| **Memory Leak** | Valgrind / ASAN | Weekly CI |
| **Throughput Floor** | wrk benchmark | Release |

### 4.4 Memory Safety Verification (Rust↔Python Boundary)

> [!CAUTION]
> These tests verify no memory issues at the language boundary.

| Test ID | Test Name | Tool | Pass Criteria |
|:---|:---|:---|:---|
| **MEM-001** | Use-After-Free | Miri | No violations |
| **MEM-002** | Reference Leaks | PyO3 debug mode | Refcount stable |
| **MEM-003** | Double-Free | ASAN | No errors |
| **MEM-004** | GIL Deadlock | Timeout wrapper | No hangs > 5s |

---

## 5. Measurement Methodology

### 5.1 Benchmarking Tools

| Tool | Purpose | Command |
|:---|:---|:---|
| **wrk** | HTTP throughput | `wrk -t4 -c100 -d30s http://localhost:8000/` |
| **hyperfine** | Cold start | `hyperfine 'velo run main:app --once'` |
| **py-spy** | Python profiling | `py-spy record -o profile.svg --pid $PID` |
| **heaptrack** | Memory profiling | `heaptrack ./target/release/velo` |

### 5.2 Test Environment Requirements

| Requirement | Specification |
|:---|:---|
| **CPU** | Dedicated cores (no contention) |
| **Network** | localhost / loopback only |
| **Warmup** | 10s before measurement |
| **Iterations** | Minimum 3 runs, report avg |

---

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|:---|:---|:---|
| **io_uring unavailable in containers** | High | Fallback to epoll (default) |
| **uvloop installation fails** | Medium | Graceful fallback to asyncio |
| **GIL contention at boundary** | High | Gate L: Minimize GIL holding |
| **Memory leak at Rust↔Python** | Critical | MEM-001 through MEM-004 tests |

---

## 7. Sign-off Criteria

Before claiming performance improvements in production:

- [ ] All PERF-72-* tests pass
- [ ] All STRESS-* tests pass
- [ ] All MEM-* tests pass
- [ ] No P99 latency regression > 10%
- [ ] Memory stable over 4-hour soak test
