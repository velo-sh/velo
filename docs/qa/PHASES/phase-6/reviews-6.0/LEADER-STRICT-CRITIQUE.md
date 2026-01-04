# LEADER STRICT CRITIQUE: RFC-0009 QA Working Group

> **Role**: Agent Leader (Strict Auditor)  
> **Objective**: Contrast WG implementations against P0/P1 Expert Findings.  
> **Status**: 🔴 CRITICAL GAPS IDENTIFIED  

---

## 1. Audit vs Python Core Expert (P0-001/002)

| Expert Requirement | WG Implementation | Critique/Finding |
|--------------------|-------------------|------------------|
| **`__path__` Mutation** | `FUNC-601` | **TOO SHALLOW**. Only tests a single levels. Experts warned about *recursive* mutation. If `pkg.a` is mutated, `pkg.a.b` MUST fall back. |
| **Hook Interception** | `FUNC-602` | **PASS**. Correctly verifies `builtins.__import__` parity. |
| **Namespace Packages** | **MISSING** | **FAULT**. No test for "split roots" where one root is in the bundle and another is on disk (PEP 420). |

**Leader Mandate**: Agent B MUST implement `FUNC-601-EXT` (Recursive path mutation) and `FUNC-605` (Namespace Clashing).

---

## 2. Audit vs Performance Expert (P0-003)

| Expert Requirement | WG Implementation | Critique/Finding |
|--------------------|-------------------|------------------|
| **Deserialize Latency** | `PERF-601` | **WEAK**. Uses a mocked metrics check. Experts demanded a *release build* benchmark under high memory pressure. |
| **Heap Allocations** | **MISSING** | **FAULT**. No check for string key allocation overhead. |

**Leader Mandate**: Agent B MUST add `PERF-606` (Pressure Deserialization) with high module counts (5,000).

---

## 3. Audit vs QA Expert (P0-008 - Negative Testing)

| Expert Requirement | WG Implementation | Critique/Finding |
|--------------------|-------------------|------------------|
| **Semantic Invalidation**| **MISSING** | **CRITICAL FAULT**. WG only tested *bit-flipping*. Experts demanded tests for *semantically invalid graphs* (e.g., hidden cycles, edges to non-existent modules). |
| **Rkyv Zero-Copy** | `SEC-601` | **PASS**. Bit-flipping is a good start, but insufficient. |

**Leader Mandate**: Agent C MUST implement `NEG-601` (Cyclic Graph Hack) to ensure the loader doesn't hang on an undetected cycle.

---

## 4. Audit vs Security (H-8, H-10)

| Invariant | WG Implementation | Critique/Finding |
|-----------|-------------------|------------------|
| **H-8 Integrity** | `SEC-601` | **WEAK**. Tampering at the end of file might miss the root pointer. |
| **H-10 Sandbox** | `SEC-602` | **PLACEHOLDER**. NO ACTUAL TEST. |
| **H-10 Arch Pinning** | `SEC-603` | **PASS**. Correct start. |

**Leader Mandate**: Agent C MUST replace placeholders with **actual byte-level injectors** for path traversal and Rkyv bombs.

---

## 🎯 Summary of "找茬" Points
1. **Agent A**: Missing "Wide DAG" stress.
2. **Agent B**: Missing Namespace collision tests.
3. **Agent C**: Failure to provide actual sandboxing traversal tests (SEC-602).

**Consensus**: The WG has been "lazy" with the complex failure modes identified by the Experts. I am ordering a **Hardening Sprint** immediately.

---
**Agent Leader Sign-off**: 🧪 Senior QA (Strict Mode ON)
