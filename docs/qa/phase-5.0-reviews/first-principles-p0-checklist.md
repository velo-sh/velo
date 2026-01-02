# Phase 5.0: First Principles P0 Checklist (Revised)

> **Date**: 2026-01-03  
> **Based on**: QA_REFLECTION_first_principles.md

---

## Core Mindset Correction

| Previous Thinking | Correct Thinking |
|-------------------|------------------|
| "Find security holes" | **"Verify functionality works"** |
| Start from edge cases | **Start from core** |
| Test coverage = quality | **Functional verification = quality** |

---

## New P0 Checklist (Correct Order)

### P0-A: Functionality Verification (Must pass first)

| ID | Test | Status |
|----|------|--------|
| **FP-L0-01** | `velo build` creates bundle | RFC lacks acceptance criteria |
| **FP-L0-02** | `velo run --fast` runs program | RFC lacks acceptance criteria |
| **FP-L0-03** | Program output is correct | RFC lacks acceptance criteria |
| **FP-L1-01** | Cold start actually faster (vs CPython) | No real benchmark |
| **FP-L1-02** | FastAPI project works normally | No E2E test |

### P0-B: Failure Recovery (After functionality passes)

| ID | Test | Status |
|----|------|--------|
| **FP-L2-01** | Corrupted bundle -> Fallback runs normally | TBD |
| **FP-L2-02** | Fingerprint change -> Auto rebuild | TBD |

### P0-C: Security Verification (After L0-L2 pass)

| ID | Test | Original Priority | New Priority |
|----|------|-------------------|--------------|
| AUDIT-006 | Hash coverage | P0 | **P1** |
| AUDIT-011 | Symlink | P0 | **P1** |
| AUDIT-009 | Path check | P0 | **P1** |

---

## RFC-0006 Missing Items

Architect must supplement:

1. **Section 3.6 Acceptance Criteria**
   - Level 0 Smoke test definition
   - Level 1 user journey definition
   - Performance acceptance standards (quantified)

2. **Benchmark Evidence**
   - Real project benchmark results
   - Cross-environment comparison data

---

**Conclusion**: Security testing is premature before functionality is verified.
