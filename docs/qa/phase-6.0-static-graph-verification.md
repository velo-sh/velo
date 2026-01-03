# RFC-0009: Static Import Graph — Verification Protocol

> **Version**: 1.0 (QA Expert Group Hardened)  
> **Target**: Velo v0.6.0  
> **Primary RFC**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)

---

## 1. Multi-Tiered Testing Strategy

This protocol follows Velo's standard tiered testing model, with specific focus on graph integrity and runtime fallback.

| Tier | Focus | Tooling |
|------|-------|---------|
| **L0: Unit** | `ImportGraph` serialization, PHF generation, record packing | `cargo test` |
| **L1: Integration** | `velo build` graph extraction, `VeloFinder` hook logic | `pytest` |
| **L2: E2E** | Cold start of Django/FastAPI projects with graph enabled | `qa/e2e_zygote.py` |
| **L3: Adversarial** | Corruption, Fuzzing, Invalidation, SCC Edge Cases | `cargo fuzz`, `qa/stress/` |
| **L4: Platform** | macOS vs. Ubuntu 22.04+ (mmap hints, page size) | CI (Dedicated Runners) |
| **L5: Perf** | 500μs deserialize latency, 0 stat() calls | `perf`, `strace` |

---

## 2. Destructive & Adversarial (L3) Test Cases

### 🛠️ TC-NEG-001: Rkyv Byte Corruption
- **Goal**: Ensure the loader does not crash on malformed graph data.
- **Action**: Use a hex editor or utility to flip bits in the Import Graph Section of a valid `.veloc` bundle.
- **Expected**: `bytecheck` fails; loader emits `LoaderError::GraphInvalid` and falls back to standard Python import.

### 🛠️ TC-NEG-002: Invalid Pool Offsets
- **Goal**: Prevent out-of-bounds access in the flattened dependency pool.
- **Action**: Manually craft a `ModuleRecord` where `pool_start + pool_len > dependency_pool.len()`.
- **Expected**: Runtime bounds check prevents crash; fallback to standard import.

### 🛠️ TC-NEG-003: Secret Cycles (SCC Failure)
- **Goal**: Ensure behavior is defined if a cycle bypasses build-time detection.
- **Action**: Inject a cycle into the load order.
- **Expected**: Python's `ImportError: circular import` is preserved exactly as CPython.

---

## 3. Scale & Stress Tests (L3)

### 📈 TC-STR-001: "Hard Limit" Enforcement
- **Goal**: Verify CI/Build failure at 5000 modules.
- **Action**: Generate a synthetic project with 5,001 empty modules.
- **Expected**: `velo build` fails with `LimitError: MaxGraphSizeExceeded`.

### 📈 TC-STR-002: Deep Dependency DAG
- **Goal**: Verify p99 latency on extreme tree depths.
- **Action**: Build a project with a 100-level deep linear dependency chain: `m0 -> m1 -> m2 ... -> m100`.
- **Expected**: Graph deserialization remains under 500μs; PHF lookup remains O(1).

---

## 4. Platform & Environment (L4)

### 🔗 TC-ENV-001: Symlink Disparity
- **Goal**: Ensure graph and filesystem remain in sync for symlinks.
- **Action**: `import symlinked_mod`; update symlink to point to a different file.
- **Expected**: `source_hash` mismatch detected; graph rebuild triggered.

### 📦 TC-ENV-002: Namespace Package Resolution
- **Goal**: Verify PEP 420 compatibility.
- **Action**: Multiple bundles contributing modules to the same namespace.
- **Expected**: `VeloFinder` correctly merges graph entries with `sys.path` search.

---

## 5. Performance Validation (L5)

| Target | Command | Success Criteria |
|--------|---------|------------------|
| **Deserialization** | `velo run --profile` | `graph_deserialize_latency_us` < 500 |
| **I/O Elimination** | `strace -e stat velo run` | 0 `stat()` calls for modules in graph |
| **Memory Ceiling** | `valgrind --tool=massif` | Heap usage peak < 200KB overhead |

---

## 📋 Approval Matrix

- [x] Security Lead (ID-LOCK-001)
- [x] QA Lead (simulated)
- [x] DevOps Lead (simulated)
