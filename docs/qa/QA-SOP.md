# QA Standard Operating Procedure (SOP)

> Derived from Phase 6.0 QA Working Group Experience
> Version 1.0 | 2026-01-04

---

## Table of Contents

1. [Overview](#1-overview)
2. [Organizational Structure](#2-organizational-structure)
3. [Phase 0: Pre-Work & Architecture Alignment](#3-phase-0-pre-work--architecture-alignment)
4. [Phase 1: Test Design & Implementation](#4-phase-1-test-design--implementation)
5. [Phase 2: Multi-Agent Review Process](#5-phase-2-multi-agent-review-process)
6. [Phase 3: External Expert Audit](#6-phase-3-external-expert-audit)
7. [Phase 4: Verification & Developer Handoff](#7-phase-4-verification--developer-handoff)
8. [Phase 5: Defect Management](#8-phase-5-defect-management)
9. [Phase 6: Final Delivery & Sign-off](#9-phase-6-final-delivery--sign-off)
10. [Appendix: Checklists & Templates](#10-appendix-checklists--templates)

---

## 1. Overview

### 1.1 Purpose

This SOP defines the complete QA workflow for high-quality, reproducible quality assurance work. It is designed to be reused across all future phases and projects.

### 1.2 Core Principles

| Principle | Description |
|:---|:---|
| **Zero Bug Policy** | No unresolved bugs enter production; all failures must be PASSED, XFAIL (with justification), or BLOCKED |
| **Design-First Testing** | Tests are designed against RFC/Architecture specs, not implementation |
| **Multi-Agent Review** | Multiple specialized agents review from different perspectives |
| **Fail-Fast** | Abort early on critical issues; don't waste time on doomed runs |
| **Evidence-Based Delivery** | Every verdict must have reproducible evidence |

### 1.3 Key Roles

```
┌─────────────────────────────────────────────────────────────────┐
│                     QA Working Group                             │
├─────────────────────────────────────────────────────────────────┤
│  QA Leader           - Final sign-off, architecture alignment   │
│  Agent A (Edge)      - Edge cases, scale limits, boundary tests │
│  Agent B (Stability) - Stress tests, concurrency, reliability   │
│  Agent C (Security)  - Security invariants, attack vectors      │
│  External Experts    - Independent review, Python Core, Perf    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Organizational Structure

### 2.1 QA Working Group Formation

```
Phase Start → Form Working Group → Assign Roles → Kick-off Meeting
```

**Required Roles:**
1. **QA Leader** (1 person)
   - Owns final verdict (APPROVED / REJECTED / CONDITIONALLY APPROVED)
   - Ensures architecture alignment
   - Coordinates between agents
   - Reports to stakeholders

2. **Specialized Agents** (2-4 agents)
   - Each agent owns a specific testing domain
   - Agents work in parallel on different test suites
   - Must submit findings independently before cross-review

3. **External Experts** (called in as needed)
   - Independent reviewers for critical decisions
   - Python Core expertise, Performance expertise, Security expertise
   - Must document ALL findings, even minor ones

### 2.2 Communication Structure

```
                    ┌─────────────┐
                    │  QA Leader  │
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Agent A  │    │ Agent B  │    │ Agent C  │
    │ (Edge)   │    │(Stability)│   │(Security)│
    └──────────┘    └──────────┘    └──────────┘
           │               │               │
           └───────────────▼───────────────┘
                    Cross-Review
```

**Communication Channels:**
- **docs/qa/phase-X-reviews/** - Review documents
- **docs/qa/defects/** - Defect reports (DEF-XX-XXX)
- **docs/qa/arch/** - Architecture decision requests (ARCH-XX-XXX)

---

## 3. Phase 0: Pre-Work & Architecture Alignment

### 3.1 RFC/Architecture Review

**Before ANY test is written, the QA Leader MUST:**

1. **Read the RFC/Design Document thoroughly**
   ```
   docs/rfcs/RFC-XXXX-feature-name.md
   ```

2. **Identify testable requirements**
   - Extract all "MUST", "SHALL", "SHOULD" statements
   - Create requirement-to-test mapping table

3. **Identify security invariants**
   - List all H-X (Hardening) requirements
   - Verify each invariant has at least one test

4. **Identify performance requirements**
   - Extract latency thresholds
   - Identify scaling limits

### 3.2 Architecture Alignment Checklist

```markdown
## Architecture Alignment Checklist

- [ ] RFC document read and understood
- [ ] All MUST requirements extracted (count: ___)
- [ ] All security invariants identified (H-1 through H-N)
- [ ] Performance thresholds documented
- [ ] Edge cases identified from design
- [ ] Known limitations documented
- [ ] Test matrix created (Framework × Scale × Mode)
```

### 3.3 Tier Definition

Define test tiers based on criticality:

| Tier | Description | Run Frequency | Failure Policy |
|:---:|:---|:---|:---|
| **L0** | Core correctness (Golden Path) | Every commit | MUST PASS |
| **L1** | Feature tests | Every PR | MUST PASS |
| **L2** | Edge cases | Daily | SHOULD PASS or XFAIL |
| **L3** | Stress/Scale | Weekly | Documented if fail |
| **L4** | Security | Every release | MUST PASS |
| **L5** | Performance regression | Nightly | Baseline comparison |

---

## 4. Phase 1: Test Design & Implementation

### 4.1 Test Suite Structure

```
tests/qa/
├── conftest.py                    # Shared fixtures
├── test_e2e_golden_path.py        # L0: Core correctness
├── test_phase6_agent_a_edge.py    # L2: Edge cases
├── test_phase6_agent_b_stability.py
├── test_phase6_agent_c_security.py
├── test_phase6_integration.py     # L1: Integration
└── test_phase6_perf_regressions.py # L5: Performance
```

### 4.2 Test Naming Convention

```
test_<TIER>_<ID>_<descriptive_name>

Examples:
- test_L0_1_ast_dependency_classification
- test_EDGE_601_deep_dependency_dag
- test_SEC_604_rkyv_bomb_protection
- test_GOLD_001_triad_full_cycle
```

### 4.3 Test Implementation Rules

1. **Isolated Environment**
   - Each test MUST use `isolated_env` fixture
   - No test pollution between runs

2. **Explicit Assertions**
   - Assert exact expected values, not just "non-null"
   - Include failure messages with context

3. **Minimal Dependencies**
   - Install only required packages in test
   - Use `env.install("package")` pattern

4. **Reproducible**
   - No random seeds without documentation
   - Deterministic test data

### 4.4 Agent Task Assignment

```markdown
## Agent A (Edge) - test_phase6_agent_a_edge.py
- [ ] EDGE-601: Deep dependency chains
- [ ] EDGE-602: String interning at scale
- [ ] EDGE-603: TOCTOU symlink swap
- [ ] EDGE-604: Hard limit gating
- [ ] EDGE-605: Wide DAG memory stress

## Agent B (Stability) - test_phase6_agent_b_stability.py
- [ ] FUNC-601: Recursive path mutation
- [ ] FUNC-602: Import hook interception
- [ ] FUNC-605: Namespace package clash
- [ ] L4-1: Dynamic import fallback
- [ ] L4-2: Soft dependency no preload

## Agent C (Security) - test_phase6_agent_c_security.py
- [ ] SEC-601: Malicious bytecode injection
- [ ] SEC-602: Symlink escape
- [ ] SEC-603: Reserved name collision
- [ ] SEC-604: rkyv bomb protection
```

---

## 5. Phase 2: Multi-Agent Review Process

### 5.1 Independent Review Phase

**Each agent reviews independently BEFORE cross-review:**

1. **Agent submits findings to:**
   ```
   docs/qa/phase-X-reviews/AGENT-A-FINDINGS.md
   docs/qa/phase-X-reviews/AGENT-B-FINDINGS.md
   docs/qa/phase-X-reviews/AGENT-C-FINDINGS.md
   ```

2. **Finding format:**
   ```markdown
   ## Finding: [ID]
   
   **Severity:** P0/P1/P2/P3
   **Category:** Bug / Design Gap / Test Issue / Enhancement
   **Description:** ...
   **Evidence:** (command, output, screenshot)
   **Recommendation:** ...
   ```

### 5.2 Cross-Review Phase

After independent submission, agents cross-review:

```
Agent A reviews → Agent B's findings
Agent B reviews → Agent C's findings
Agent C reviews → Agent A's findings
```

**Cross-review checklist:**
- [ ] Findings reproducible?
- [ ] Severity accurate?
- [ ] Any missed edge cases?
- [ ] Overlapping findings consolidated?

### 5.3 Leader Gap Analysis

QA Leader performs final gap analysis:

```
docs/qa/phase-X-reviews/LEADER-GAP-ANALYSIS.md
```

**Leader responsibilities:**
1. **Consolidate all findings**
2. **Verify architecture alignment**
3. **Identify patterns across agents**
4. **Prioritize P0/P1 issues**
5. **Request external review if needed**

---

## 6. Phase 3: External Expert Audit

### 6.1 When to Call External Experts

**MUST call external experts when:**
- P0 security vulnerability discovered
- Architecture design unclear/ambiguous
- Performance regression > 2x baseline
- Cross-cutting concern affects multiple components
- Python internals behavior unclear

### 6.2 Expert Review Process

1. **Request expert review:**
   ```markdown
   ## Expert Review Request
   
   **Domain:** Python Core / Performance / Security
   **RFC Reference:** RFC-0009 Section 5.3
   **Questions:**
   1. Is the __path__ mutation handling correct?
   2. Should we use CPython fallback for TYPE_CHECKING imports?
   ```

2. **Expert submits findings:**
   ```
   docs/qa/phase-X-reviews/EXPERT-PYTHON-CORE.md
   docs/qa/phase-X-reviews/EXPERT-PERFORMANCE.md
   ```

3. **Finding classification:**
   - **P0 (Critical):** MUST FIX before merge
   - **P1 (Must Fix):** MUST FIX, can be follow-up PR
   - **P2 (Should Fix):** Good to have
   - **P3 (Enhancement):** Future work

### 6.3 Architecture Issue Escalation

**If expert finds architecture issues:**

1. **Create ARCH document:**
   ```
   docs/qa/arch/ARCH-60-001-Design-Decisions.md
   ```

2. **Report to Architect immediately**
   - Do NOT wait until end of QA
   - Block dependent tests until resolution

3. **Document decision:**
   ```markdown
   ## Architecture Decision: ARCH-60-001
   
   **Question:** Should bundles auto-invalidate on symlink change?
   **Architect Decision:** No, bundle is compile-time snapshot (by design)
   **QA Action:** Mark test as XFAIL with reason
   ```

---

## 7. Phase 4: Verification & Developer Handoff

### 7.1 Developer Fix Verification

**When developer pushes fixes:**

1. **Pull latest code**
   ```bash
   git pull origin <branch>
   cargo build --release
   ```

2. **Run targeted tests**
   ```bash
   uv run pytest tests/qa/test_<affected>.py -v
   ```

3. **Verify fix, watch for regressions**
   - Run FULL test suite after targeted pass
   - Compare with previous baseline

4. **Update defect status**
   ```markdown
   **Status:** FIXED → VERIFIED
   **Verified By:** QA Leader
   **Commit:** abc1234
   ```

### 7.2 Regression Detection Protocol

**"Peeling the Onion" Pattern:**

When a fix causes new failures:
1. Stop and analyze
2. Check if test harness issue or real regression
3. Verify test syntax/environment first
4. Then verify actual behavior
5. Document root cause

### 7.3 Pre-Delivery Checklist

```markdown
## Developer Pre-Delivery Checklist

Before submitting for QA:
- [ ] `cargo test` - All unit tests pass
- [ ] `cargo clippy -- -D warnings` - No warnings
- [ ] `uv run pytest tests/qa/test_e2e_golden_path.py` - E2E pass
- [ ] `uv run pytest tests/qa/test_phase6_*.py` - Agent tests pass

Submit this checklist with PR.
```

---

## 8. Phase 5: Defect Management

### 8.1 Defect Report Format

```
docs/qa/defects/DEF-60-XXX-Short-Name.md
```

```markdown
# DEF-60-XXX: Short Descriptive Name

**Priority:** P0 / P1 / P2 / P3
**Status:** OPEN / IN PROGRESS / FIXED / VERIFIED / WONTFIX
**Reporter:** Agent A / QA Leader
**Assignee:** Developer Name

## Summary
One-line description of the issue.

## Reproduction
```bash
exact commands to reproduce
```

## Expected Behavior
What should happen.

## Actual Behavior
What actually happens (include error messages).

## Root Cause Analysis
(If known)

## Suggested Fix
(If known)

---
**QA Signature:** Velo QA Working Group
```

### 8.2 Master Defect Report

Maintain consolidated defect tracking:

```
docs/qa/defects/PHASE_X_MASTER_DEFECTS.md
```

```markdown
# Phase X.0 Master Defect Report

**QA Verdict:** APPROVED / CONDITIONALLY APPROVED / REJECTED
**Build Hash:** abc1234
**Date:** YYYY-MM-DD

## Summary

| Priority | Open | Fixed | Verified | Won't Fix |
|:---:|:---:|:---:|:---:|:---:|
| P0 | 0 | 2 | 2 | 0 |
| P1 | 0 | 3 | 3 | 0 |
| P2 | 2 | 0 | 0 | 0 |

## P0 Critical Issues
- DEF-60-007: Bundle Hash Mismatch - **VERIFIED**
...
```

### 8.3 XFAIL Justification Policy

**When marking test as XFAIL:**

1. **MUST have documented reason**
   ```python
   @pytest.mark.xfail(reason="P2: __path__ mutation requires CPython fallback (by design)")
   ```

2. **MUST link to architecture decision if applicable**
   ```python
   @pytest.mark.xfail(reason="ARCH-60-001: Bundle is compile-time snapshot")
   ```

3. **MUST NOT use XFAIL to hide real bugs**
   - P0/P1 issues CANNOT be XFAIL'd
   - Only design-intentional gaps allowed

---

## 9. Phase 6: Final Delivery & Sign-off

### 9.1 QA Verdict Criteria

| Verdict | Criteria |
|:---|:---|
| **APPROVED** | All tests PASS, no P0/P1 open, E2E verified |
| **CONDITIONALLY APPROVED** | E2E PASS, no P0 open, P1 has remediation plan |
| **REJECTED** | P0 open OR E2E failed OR critical regression |

### 9.2 Final Sign-off Checklist

```markdown
## QA Leader Final Sign-off

**Phase:** 6.0
**Date:** YYYY-MM-DD
**Verdict:** CONDITIONALLY APPROVED

### Test Results Summary
- E2E Golden Path: 9/9 PASSED ✅
- Rust Unit Tests: 91/91 PASSED ✅
- Agent A (Edge): 7/10 PASSED, 3 XFAIL
- Agent B (Stability): 6/6 PASSED ✅
- Agent C (Security): 4/4 PASSED ✅
- Performance: Baseline established ✅

### Defect Summary
- P0: 0 open (all verified)
- P1: 0 open (all verified)
- P2: 3 documented (XFAIL)
- P3: 2 enhancement requests

### Sign-off
- [ ] All P0/P1 resolved or mitigated
- [ ] E2E suite passes
- [ ] Architecture alignment verified
- [ ] Performance baselines established
- [ ] Documentation complete

**QA Leader Signature:** _______________
**Date:** _______________
```

### 9.3 Deliverables Checklist

```markdown
## Phase X.0 QA Deliverables

### Documentation
- [ ] Master Defect Report (PHASE_X_MASTER_DEFECTS.md)
- [ ] Agent Review Documents (phase-X-reviews/)
- [ ] Leader Gap Analysis
- [ ] Architecture Decision Requests (if any)

### Test Artifacts
- [ ] test_e2e_golden_path.py
- [ ] test_phase6_agent_*.py
- [ ] test_phase6_integration.py
- [ ] test_phase6_perf_regressions.py
- [ ] conftest.py (shared fixtures)

### Benchmark Artifacts
- [ ] benchmark_framework_scale.py
- [ ] benchmark_velo_vs_cpython.py
- [ ] FRAMEWORK_SCALE_BASELINES.md
- [ ] comparison_results.json

### Process Artifacts
- [ ] Pre-delivery checklist for developers
- [ ] QA final sign-off document
```

---

## 10. Appendix: Checklists & Templates

### 10.1 Quick Reference: QA Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        QA WORKFLOW                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  PHASE 0: Pre-Work                                                   │
│  ├── Read RFC/Architecture                                           │
│  ├── Create requirement mapping                                      │
│  └── Define test tiers                                              │
│                                                                      │
│  PHASE 1: Test Design                                               │
│  ├── Implement test suites                                          │
│  ├── Assign agents                                                  │
│  └── Run initial pass                                               │
│                                                                      │
│  PHASE 2: Multi-Agent Review                                        │
│  ├── Independent agent testing                                      │
│  ├── Cross-review                                                   │
│  └── Leader gap analysis                                            │
│                                                                      │
│  PHASE 3: External Expert Audit (if needed)                         │
│  ├── Request expert review                                          │
│  ├── Collect findings                                               │
│  └── Escalate architecture issues                                   │
│                                                                      │
│  PHASE 4: Verification                                              │
│  ├── Verify developer fixes                                         │
│  ├── Regression detection                                           │
│  └── Update defect status                                           │
│                                                                      │
│  PHASE 5: Defect Management                                         │
│  ├── Maintain master defect report                                  │
│  ├── Track P0/P1 to resolution                                      │
│  └── Document XFAIL justifications                                  │
│                                                                      │
│  PHASE 6: Delivery                                                  │
│  ├── Final sign-off                                                 │
│  ├── Verdict determination                                          │
│  └── Deliverables handoff                                           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.2 Template: Agent Findings

```markdown
# Agent [A/B/C] Findings Report

**Phase:** X.0
**Agent:** Agent A (Edge)
**Date:** YYYY-MM-DD

## Test Execution Summary

| Test ID | Status | Notes |
|:---|:---:|:---|
| EDGE-601 | PASS | |
| EDGE-602 | FAIL | See Finding #1 |
| EDGE-603 | XFAIL | Design limitation |

## Findings

### Finding #1: [Short Title]

**Severity:** P1
**Test:** EDGE-602
**Description:**
...

**Reproduction:**
```bash
command here
```

**Evidence:**
```
output here
```

**Recommendation:**
...

---
**Agent Signature:** Agent A
```

### 10.3 Template: Architecture Decision Request

```markdown
# ARCH-XX-XXX: [Title]

**Status:** PENDING / APPROVED / REJECTED
**Reporter:** QA Working Group
**Date:** YYYY-MM-DD

## Question for Architect

[Clear question that needs architectural decision]

## Context

[Background information]

## Options

### Option 1: [Name]
- Pros: ...
- Cons: ...

### Option 2: [Name]
- Pros: ...
- Cons: ...

## Architect Decision

**Decision:** [Architect fills this]
**Rationale:** [Architect fills this]
**Date:** [Architect fills this]

## QA Action

Based on decision, QA will:
- [ ] Update tests accordingly
- [ ] Mark affected tests as XFAIL if design-intentional
- [ ] Document in Master Defect Report
```

---

## Revision History

| Version | Date | Author | Changes |
|:---:|:---|:---|:---|
| 1.0 | 2026-01-04 | QA Working Group | Initial version from Phase 6.0 retrospective |

---

**Velo QA Working Group** | SOP v1.0
