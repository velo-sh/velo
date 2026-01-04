# Velo QA Documentation Library

> **QA Working Group Shared Assets**
> Last Updated: 2026-01-04

---

## 🎯 Quick Start

| If you want to... | Read this |
|:---|:---|
| **Start QA work on a new Phase** | [QA-SOP.md](./QA-SOP.md) |
| **Understand testing methodology** | [tiered-testing-guide.md](./tiered-testing-guide.md) |
| **Check/create defect reports** | [defects/](./defects/) |
| **Run benchmarks** | [../../benchmarks/](../../benchmarks/) |
| **Explore all knowledge assets** | [KNOWLEDGE_TREASURY.md](./KNOWLEDGE_TREASURY.md) |


---

## 📚 Document Categories

### 🔴 TIER 1: Master Standards (MUST READ)

These are the **authoritative** QA documents. All QA work must follow these standards.

| Document | Lines | Purpose |
|:---|:---:|:---|
| **[QA-SOP.md](./QA-SOP.md)** | **1214** | **Master Standard Operating Procedure** |
| [tiered-testing-guide.md](./tiered-testing-guide.md) | 348 | Tiered testing methodology (Tier 0-3, L0-L6) |
| [QA_REFLECTION_first_principles.md](./QA_REFLECTION_first_principles.md) | 110 | Testing philosophy & lessons learned |

### 🟡 TIER 2: Templates & Checklists

Reusable templates for QA activities.

| Document | Purpose |
|:---|:---|
| [QA_CHECKLIST_TEMPLATE.md](./QA_CHECKLIST_TEMPLATE.md) | Manual QA checklist template |
| [QA-STANDARDS-ALIGNMENT.md](./QA-STANDARDS-ALIGNMENT.md) | Standards alignment audit (internal) |

### 🟢 TIER 3: Phase-Specific Records

Historical records organized by Phase. Use these as reference for future work.

#### Phase 6.x (Static Graph)
| Document | Type |
|:---|:---|
| [phase-6.0-static-graph-verification.md](./phase-6.0-static-graph-verification.md) | Verification report |
| [phase-6.0-reviews/](./phase-6.0-reviews/) | Expert review documents (18 files) |
| [phase-6.1-qa-framework.md](./phase-6.1-qa-framework.md) | QA framework |
| [phase-6.1-multi-agent-tests.md](./phase-6.1-multi-agent-tests.md) | Multi-agent test plan |
| [phase-6.1-reviews/](./phase-6.1-reviews/) | Review documents |

#### Phase 5.x (Zygote)
| Document | Type |
|:---|:---|
| [phase-5.0-qa-framework.md](./phase-5.0-qa-framework.md) | QA framework |
| [phase-5.0-reviews/](./phase-5.0-reviews/) | Expert review documents (18 files) |

#### Phase 4.x (Security)
| Document | Type |
|:---|:---|
| [phase-4.0-defect-report.md](./phase-4.0-defect-report.md) | Defect report |
| [phase-4.0-task-handoff.md](./phase-4.0-task-handoff.md) | Task handoff |
| [phase-4.1-task-handoff.md](./phase-4.1-task-handoff.md) | Task handoff |

#### Phase 3.x (Core)
| Document | Type |
|:---|:---|
| [phase-3-test-matrix.md](./phase-3-test-matrix.md) | Test matrix |
| [phase-3-multi-agent-tests.md](./phase-3-multi-agent-tests.md) | Multi-agent tests |
| [phase-3-defect-report.md](./phase-3-defect-report.md) | Defect report |
| [phase-3.5-test-matrix.md](./phase-3.5-test-matrix.md) | Test matrix |
| [phase-3.5-multi-agent-tests.md](./phase-3.5-multi-agent-tests.md) | Multi-agent tests |
| [phase-3.5-test-gap-analysis.md](./phase-3.5-test-gap-analysis.md) | Gap analysis |
| [phase-3.5-defect-report.md](./phase-3.5-defect-report.md) | Defect report |

#### Phase 1.x (Foundation)
| Document | Type |
|:---|:---|
| [phase-1.5-test-matrix.md](./phase-1.5-test-matrix.md) | Test matrix |

### 🔵 TIER 4: Defects & Issues

Active and historical defect tracking.

| Location | Contents |
|:---|:---|
| [defects/](./defects/) | Master defect reports (5 files) |
| [DEF-003-zygote-prewarm.md](./DEF-003-zygote-prewarm.md) | Zygote prewarm issue |
| [DEV-FIX-001-zygote-auto-preload.md](./DEV-FIX-001-zygote-auto-preload.md) | Developer fix record |
| [BUG-REPORT-CODE-COVERAGE-BLAKE3.md](./BUG-REPORT-CODE-COVERAGE-BLAKE3.md) | BLAKE3 coverage issue |

### 🟣 TIER 5: Requirements & Specifications

QA requirements for specific features.

| Document | Feature |
|:---|:---|
| [QA-REQ-001-zygote-preload.md](./QA-REQ-001-zygote-preload.md) | Zygote preload |
| [QA-REQ-002-zygote-async.md](./QA-REQ-002-zygote-async.md) | Zygote async |
| [QA-REQ-003-bundle-config.md](./QA-REQ-003-bundle-config.md) | Bundle config |
| [QA-REQ-004-security-hardening.md](./QA-REQ-004-security-hardening.md) | Security hardening |

### ⚪ TIER 6: Miscellaneous

Other important documents.

| Document | Purpose |
|:---|:---|
| [arch/](./arch/) | Architecture decision records |
| [arch-handover-2026-01-02.md](./arch-handover-2026-01-02.md) | Architecture handover |
| [QA-AUDIT-RFC-0009.md](./QA-AUDIT-RFC-0009.md) | RFC-0009 audit |
| [security_blueprints.md](./security_blueprints.md) | Security blueprints |
| [framework-battle-plan.md](./framework-battle-plan.md) | Framework benchmark plan |
| [qa_integrity_report_v2.md](./qa_integrity_report_v2.md) | Integrity report |
| [benchmarks/](./benchmarks/) | Benchmark baselines |

---

## 📊 Statistics

| Category | Count | Total Lines |
|:---|:---:|:---:|
| Master Standards | 3 | ~1,700 |
| Templates | 2 | ~180 |
| Phase Records | 15+ | ~60,000 |
| Defect Records | 8+ | ~5,000 |
| Requirements | 4 | ~8,000 |
| **Total** | **33+ files** | **~75,000+ lines** |

---

## 🔗 External References

| Document | Location |
|:---|:---|
| [Benchmark Suite](../../benchmarks/) | Performance benchmarks |
| [Test Files](../../tests/qa/) | Pytest test suites |
| [RFC Documents](../rfcs/) | Feature specifications |

---

## 📝 How to Use This Library

### For New QA Team Members
1. Read **[QA-SOP.md](./QA-SOP.md)** completely (1214 lines)
2. Understand **[tiered-testing-guide.md](./tiered-testing-guide.md)**
3. Review **[QA_REFLECTION_first_principles.md](./QA_REFLECTION_first_principles.md)**
4. Look at recent Phase records for examples

### For Starting a New Phase
1. Create `phase-X.Y-qa-framework.md` based on previous phases
2. Create `phase-X.Y-multi-agent-tests.md` for agent assignments
3. Create `phase-X.Y-reviews/` directory for expert reviews
4. Follow SOP workflow exactly

### For Reporting Defects
1. Use format: `DEF-{phase}-{number}`
2. Follow template in [defects/](./defects/)
3. Update master defect report after resolution

---

## 📋 Maintenance

| Task | Frequency | Owner |
|:---|:---|:---|
| Update SOP | Per Phase | QA Leader |
| Update tiered-testing-guide | As needed | QA Leader |
| Archive old phase docs | End of Phase | QA Team |
| Review standards alignment | Quarterly | QA Leader |

---

**Velo QA Working Group** | Documentation Library v1.0
