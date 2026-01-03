# RFC-0009 DevOps Expert Review

> **Reviewer Role**: 🌐 DevOps & Infrastructure Specialist  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟢 **APPROVED** (Requires standardized CI benchmark runners)

---

## Executive Summary

From a DevOps perspective, the primary risk with RFC-0009 is **benchmark drift** and **flaky performance signals** in CI environments. While the RFC specifies a benchmark environment (§5.5), executing this in a shared GitHub Actions runner will yield inconsistent results. This review mandates a "Golden Runner" strategy and CI-gated regression checks.

---

## 🟢 Strengths Acknowledged

| ID | Finding | Assessment |
|----|---------|------------|
| S-23 | **Reproducible Build (rkyv)** | The use of deterministic hashing (P1-012) ensures that the same source generates a byte-identical graph. |
| S-24 | **Static Analysis Build Step** | Decoupling graph generation into the build phase fits perfectly with standard CI/CD pipelines. |
| S-25 | **Metric Tracking** | The recommendation for `graph_miss_count` enables monitoring of optimization effectiveness in production. |

---

## 🔴 Critical Findings (P0 - Must Fix)

### P0-007: Lack of Isolated Benchmark Environment in CI

**Problem**: Standard GitHub Actions runners (especially macOS) have highly variable I/O and CPU performance. A 500μs target (§5.1) cannot be reliably measured on shared infrastructure.

**Risk Level**: 🔴 **CRITICAL** - False negatives/positives in CI.

**Recommendation**:
1. **Bare-Metal / Dedicated Runner**: Benchmarks MUST run on a dedicated, bare-metal instance with a stable kernel and NVMe SSD.
2. **Warm-up Cycles**: The CI pipeline MUST perform at least 3 warm-up runs before measuring the p50/p95.

---

## 🟡 Design Recommendations (P1 - Must Fix Before Implementation)

### P1-015: Build-Time Graph Size Regression Gating

**Problem**: The RFC specifies soft/hard limits (§5.4) but doesn't mandate **CI gating**.

**Recommendation**:
1. **CI Enforcement**: The `bundle_builder.py` MUST return a non-zero exit code if the HARD limit is exceeded during a CI build.
2. **Trend Monitoring**: Log graph size and edge density to a performance dashboard (e.g., Prometheus/Grafana) to detect slow regressions.

---

### P1-016: Dependency on Python AST Versioning

**Problem**: `python/graph_extractor.py` (§Appendix A) will run in the CI environment. If the CI uses Python 3.12 but the target is 3.11, AST changes could lead to incorrect graphs.

**Recommendation**:
1. **Hermetic Build Environment**: Use `uv` or `docker` to ensure the graph extractor runs in the *exact same* Python version as the target bundle.

---

## 🟠 Operational Considerations (P2 - Should Address)

### P2-022: Cache Invalidation Debugging

**Observation**: If a user reports "imports are broken," DevOps needs to verify if the graph is stale.

**Recommendation**: 
1. Add a command `velo inspect bundle.veloc --graph` to dump the graph source hash and module list in a human-readable format.

---

### P2-023: Artifact Size Monitoring

**Observation**: A 200KB graph is small, but if a project has 5000+ modules, it might impact bundle distribution time.

**Recommendation**: 
1. The CI build summary SHOULD include the percentage of the bundle occupied by the graph section.

---

## 🔵 Future Considerations (P3)

| ID | Suggestion |
|----|------------|
| P3-013 | Integration with OpenTelemetry for real-world `graph_deserialize` tracking. |
| P3-014 | Automated "Optimization Suggestions" in CI if many imports are falling back. |

---

## ✅ DevOps Compliance Checklist

| Requirement | Status |
|-------------|--------|
| Reproducible Artifacts | ✅ (BLAKE3 + Deterministic Hash) |
| CI-Gated Performance | ⚠️ (Requires Dedicated Runner) |
| Build-Time Safety | ✅ (Static Check) |
| Operational Visibility | ⚠️ (Requires `velo inspect`) |

---

## 📋 Approval Status

RFC-0009 is **APPROVED** with the requirement that the **Verification Plan (§6)** is updated to include **Dedicated CI Runners** and **Hard-Limit Gating**.

---

*Reviewed by: 🌐 DevOps Expert (Simulated)*  
*Review Protocol: CI/CD Stability & Performance Reproducibility Audit*
