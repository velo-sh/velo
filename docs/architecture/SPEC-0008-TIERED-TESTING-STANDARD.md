# SPEC-0008: Velo Tiered Testing Master Standard

**Status**: APPROVED (Phase 7.3 Stabilization)
**Author**: Architect
**Date**: 2026-01-14

## 1. Introduction
To maintain high velocity while ensuring industrial-grade stability, Velo employs a **Tiered Testing Strategy**. This standard defines the taxonomy, markers, and execution policies for all tests within the Velo ecosystem.

## 2. Testing Taxonomy (The Five Tiers)

Velo categorizes tests by their execution time and resource intensity.

| Tier | Marker | Duration (Target) | Scope | Execution Policy |
|:---|:---|:---|:---|:---|
| **Tier 0** | `@pytest.mark.tier0` | **< 10s** | Smoke tests, basic sanity | Every commit (local + CI) |
| **Tier 1** | `@pytest.mark.tier1` | **< 60s** | Core logic, error handling | Every PR |
| **Tier 2** | `@pytest.mark.tier2` | **< 10m** | Full functional integration | Merge to `main` |
| **Tier 3** | `@pytest.mark.tier3` | **> 10m** | Stress, resource leakage | Scheduled / Nightly |
| **Tier 4** | `@pytest.mark.chaos` | **Hours** | Flood, Chaos, Fuzzing | Manual / Pre-release |

## 3. Specialized Categories

### 3.1 Flood Tests (`@pytest.mark.flood`)
- **Focus**: High-concurrency connection loops, signal storms, and IPC buffer flooding.
- **Invariant**: Flood tests MUST be isolated from Tier 0/1 to prevent CI timeouts.
- **Execution**: Run as part of Tier 4 or dedicated performance audits.

### 3.2 Chaos Tests (`@pytest.mark.chaos`)
- **Focus**: Process killing, network Partitioning, and environment poisoning.
- **Requirement**: Must utilize `isolated_env` fixture to ensure cleanup.

### 3.3 Performance Benchmarks (`@pytest.mark.perf`)
- **Focus**: Latency gating and throughput invariants.
- **Requirement**: Must be run on **Cold Cache** as per [SPEC-0007](./SPEC-0007-PERFORMANCE-MASTER-STANDARD.md).

## 4. Execution Governance

### 4.1 CI Alignment
Tests are mapped to the Compilation Tiers defined in [SPEC-0007](./SPEC-0007-PERFORMANCE-MASTER-STANDARD.md):

- **Dev (Tier 1 Compilation)**: Runs Tier 0 and Tier 1 tests.
- **Release (Tier 2 Compilation)**: Runs Tier 0, 1, and 2 tests.
- **Production (Tier 3 Compilation)**: Runs all Tiers including Tier 3, 4, and Performance benchmarks.

### 4.2 Local Development Best Practices
- Developers should run `pytest -m "tier0 or tier1"` before pushing.
- Heavy tests (`tier3`, `chaos`) should be run in a dedicated long-running local session or CI stage.

## 6. Implementation Guide

### 6.1 GitHub Actions (CI) Workflow Example
Separate your jobs by tier to optimize runner allocation:

```yaml
jobs:
  tier-1-fast:
    name: "Tier 1: PR Fast Pass"
    if: github.event_name == 'pull_request'
    run: uv run pytest -m "tier0 or tier1"

  tier-2-main:
    name: "Tier 2: Main Integration"
    if: github.ref == 'refs/heads/main'
    run: uv run pytest -m "tier2"

  tier-4-nightly:
    name: "Tier 4: Chaos & Flood"
    if: github.event_name == 'schedule'
    run: uv run pytest -m "flood or chaos" --timeout=3600
```

### 6.2 Local Execution (Developer Dashboard)
It is recommended to use specific commands or a `Makefile` to trigger tiers:

| Goal | Command |
|:---|:---|
| **Quick Check (Safe)** | `pytest -m "tier1"` |
| **Pre-commit (Sanity)** | `pytest -m "tier0"` |
| **Heavy Debug (Careful)**| `pytest -m "tier3"` |
| **Burn-in (Destructive)**| `pytest -m "flood or chaos"` |

> [!CAUTION]
> Running Tier 4 tests locally may impact system stability and consumes significant CPU/IO. Close all IDEs and browser windows before starting.
