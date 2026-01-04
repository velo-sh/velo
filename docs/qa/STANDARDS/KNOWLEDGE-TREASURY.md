# Velo Knowledge Treasury

> **QA & Engineering Team Shared Intellectual Property**
> Mining Date: 2026-01-04

This document indexes all knowledge assets discovered across the project history, from early foundations to Phase 6.x maturity.

---

## 📊 Treasury Overview

| Source | Files | Lines | Status |
|:---|:---:|:---:|:---:|
| **Knowledge Base** | 2 KIs | 70,000+ | ✅ Institutionalized |
| **QA Documentation** | 33+ | 75,000+ | ✅ Indexed in README.md |
| **Project Standards** | 4 | 680+ | ✅ Active |
| **Agent Protocol** | 2 | 45,000+ | ✅ Master Governance |

---

## 🔴 TIER 1: Master Protocol & Governance (45KB+)

**The most valuable knowledge asset.** Contains 25+ institutionalized rituals.

### Source: `~/.gemini/antigravity/knowledge/agent_governance_and_methodology/artifacts/protocol.md`

| Section | Title | Key Content |
|:---:|:---|:---|
| §1 | **5DR Execution Cycle** | Top View → Blueprint → Execute → Verify → Deliver |
| §2 | **Role Segregation** | Architect (NO-CODE), QA (NO-SOURCE), Developer |
| §3 | **Runbook-First Workflow** | DevOps mandatory documentation |
| §5 | **Multi-Persona QA** | 4-Agent pattern (Edge/Stability/Security/Destroyer) |
| §6 | **Cross-Review Ritual** | A+B→C, B+C→A, A+C→B |
| §7 | **Git Rituals** | No-Log Policy, WAL Trap, pkill Trap, Merge Forensic |
| §8 | **Dev Hygiene** | Hardcoding Mandate, One Source of Truth |
| §9 | **Role Recovery** | The "Whoops" Defense |
| §10 | **Naming Clarity** | 见名知意, Terminology Parity |
| §11 | **Infrastructure** | Restart Ritual, Coverage Anchor, CSV Trap |
| §12 | **Documentation** | Actionable Paths, WIP Disclosure |
| §13 | **Case Studies** | Phase 3.5 Recovery, Phase 6.0 "Peeling the Onion" |
| §14 | **QA First Principles** | L0-L5 Hierarchy, Shell vs Core |
| §15 | **Sandbox Mandate** | Environment Isolation |
| §16 | **Terminology Matrix** | Fingerprint vs Detection vs Footprint |
| §17 | **Fidelity-Safety** | Dual-Mode (Runtime vs Static) |
| §18 | **One-Click Validation** | Final verification script |
| §19 | **Path Discovery** | 6-Tier Search Pattern |
| §20 | **Configuration Bridge** | CLI-to-Daemon config passing |
| §21 | **Sandwich Tactics** | Product/Strategy/Kernel balance |
| §22 | **Zero Bug Policy** | XFAIL/SKIP justification |
| §23 | **Progressive Scaling** | L1-L5 Industrial Battle |
| §24 | **Working Group SOP** | Multi-Agent coordination |
| §25 | **16-Dimension Audit** | CTO→PM→Engineer→...→Legal |

---

## 🟡 TIER 2: Velo Runtime Knowledge (Quality Assurance Master)

### Source: `~/.gemini/antigravity/knowledge/velo_runtime/artifacts/testing/quality_assurance_master.md`

| Section | Key Content |
|:---:|:---|
| §1 | Multi-Persona Strategy (Aggressor/Conservative/Security/Leader) |
| §2 | Tiered Testing Pyramid (L0-L6) |
| §3 | Phase 6.0 Static Graph Audit (RFC-0009) |
| §4 | Phase 6.1 "The Hook" Verification |
| §5 | Operational Rituals (0-stat, Signal Stress, Zombie Sweep) |
| §6 | Zero Bug Policy Enforcement |
| §7 | Progressive Scaling (L1-L5) |
| §8 | Asset Library Navigation |
| §9 | Anti-Patterns & First Principles |

---

## 🟢 TIER 3: Project Standards

### Located in: `docs/`

| Document | Lines | Key Content |
|:---|:---:|:---|
| **DEFINITION_OF_DONE.md** | 216 | Gate 1 (Dev Handoff), Gate 2 (QA Sign-off), Escalation |
| **STANDARDS.md** | 234 | Directory structure, Naming conventions, Test categories |
| **TEST_ARCHITECTURE.md** | 230 | Environment isolation, Type 1/1.5/1.6/2 tests |
| **DOCUMENTATION_GUIDELINES.md** | ~100 | Documentation standards |

---

## 🔵 TIER 4: Critical Rituals Summary

### 4.1 The 25 Institutionalized Rituals

| # | Ritual Name | When to Use |
|:---:|:---|:---|
| 1 | **5DR Cycle** | Every task |
| 2 | **Architect NO-CODE** | Architecture phases |
| 3 | **QA NO-SOURCE** | QA phases |
| 4 | **ID-LOCK-GLOBAL** | Role assignment |
| 5 | **Runbook-First** | DevOps operations |
| 6 | **Cross-Review (XR)** | High-stakes releases |
| 7 | **No-Log Policy** | Git commits |
| 8 | **WAL Trap Cleanup** | CI runners |
| 9 | **Merge Forensic** | After complex merges |
| 10 | **pkill Trap Avoidance** | Process cleanup |
| 11 | **Secure Tempdir** | Integration tests |
| 12 | **Hardcoding Mandate** | Configuration |
| 13 | **Role Recovery** | Accidental violations |
| 14 | **Clarity Mandate** | File naming |
| 15 | **Pattern Collision** | Batch edits |
| 16 | **Restart Ritual** | Config changes |
| 17 | **Coverage Anchor** | CI sync |
| 18 | **Actionable Paths** | Documentation |
| 19 | **WIP Disclosure** | Early-stage projects |
| 20 | **L0-L5 Hierarchy** | Test design |
| 21 | **Sandbox Mandate** | Integration tests |
| 22 | **One-Click Validation** | Final QA |
| 23 | **16-Dimension Audit** | Critical RFCs |
| 24 | **Zero Bug Policy** | Merge gates |
| 25 | **Peeling the Onion** | Defect investigation |

### 4.2 The 10 Anti-Patterns (FORBIDDEN)

| # | Anti-Pattern | Consequence |
|:---:|:---|:---|
| 1 | "Works on My Machine" | CI failures |
| 2 | Subprocess Silence | Hidden failures |
| 3 | E2E Skipping | Functional blind spots |
| 4 | Stale Blueprint | Test pollution |
| 5 | Shell-Only Testing | Core not verified |
| 6 | Silent Defaults | Financial poisoning |
| 7 | Host Import Leaks | Environment drift |
| 8 | Shared Temp Dirs | Non-deterministic |
| 9 | Generic File Names | Clarity loss |
| 10 | Hardcoded Fallbacks | Data corruption |

---

## 🟣 TIER 5: Case Studies (Lessons Learned)

### 5.1 Phase 3.5: "94 Tests PASS but Feature Broken"

**Problem**: Tested the "Shell" (CLI, arguments), not the "Core" (port binding).

**Lesson**: L0/L1 MUST pass before secondary tests mean anything.

### 5.2 Phase 6.0: "Peeling the Onion"

**Problem**: Functional stub (script wrapper) hid real implementation bugs.

**Layers Peeled**:
1. Layer 1: Native Move → Unmasked AST classification failure
2. Layer 2: Logic Fix → Revealed lazy loading regression
3. Layer 3: Scaling → Exposed subprocess spawn bottleneck

**Solution**: Persistent Batch Worker, Metrics Observability.

### 5.3 Phase 6.1: "15-Second Integration Timeout"

**Problem**: Standard 5s timeout insufficient for RAII supervisor loop.

**Lesson**: Institutionalized 15s timeouts for process management tests.

---

## 📋 How to Use This Treasury

### For New Team Members
1. Read `protocol.md` Sections §1, §2, §5, §14 (Core methodology)
2. Read `DEFINITION_OF_DONE.md` (Quality gates)
3. Read `TEST_ARCHITECTURE.md` (Test isolation)
4. Read `docs/qa/README.md` (QA library index)

### For Starting New Work
1. Review relevant Section from `protocol.md`
2. Follow applicable ritual
3. Reference case studies if similar situation

### For QA Work
1. Use `docs/qa/QA-SOP.md` as primary guide
2. Reference `quality_assurance_master.md` for deep knowledge
3. Apply 4-Agent pattern for critical features

---

## 📊 Statistics

| Metric | Value |
|:---|:---:|
| Total Lines of Knowledge | **120,000+** |
| Institutionalized Rituals | **25** |
| Anti-Patterns Documented | **10** |
| Case Studies | **5+** |
| Phases Covered | **1.5 - 6.1** |
| Documents | **50+** |

---

**Velo Knowledge Treasury** | v1.0 | 2026-01-04
