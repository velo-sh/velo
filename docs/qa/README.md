# Velo QA Documentation Library

> **QA Working Group Shared Assets**
> Reorganized: 2026-01-04

---

## 🎯 Quick Start

| If you want to... | Read this |
|:---|:---|
| **Start QA work on a new Phase** | [STANDARDS/QA-SOP.md](./STANDARDS/QA-SOP.md) |
| **Understand testing methodology** | [STANDARDS/TIERED-TESTING-GUIDE.md](./STANDARDS/TIERED-TESTING-GUIDE.md) |
| **Explore all knowledge assets** | [STANDARDS/KNOWLEDGE-TREASURY.md](./STANDARDS/KNOWLEDGE-TREASURY.md) |
| **Use a checklist template** | [TEMPLATES/CHECKLIST-TEMPLATE.md](./TEMPLATES/CHECKLIST-TEMPLATE.md) |
| **Review feature requirements** | [REQUIREMENTS/](./REQUIREMENTS/) |
| **Check defect reports** | [DEFECTS/](./DEFECTS/) |

---

## 🛡️ The 4 QA Commandments (Living Culture)

> *"Code compiles, documentation rots."* — Keep this library alive.

1. **Fight Entropy**: Before every Phase Kick-off, the Leader MUST scan `STANDARDS/`. If a rule isn't followed, fix the behavior or update the doc.
2. **Single Source of Truth**: Never answer process questions with oral tradition. Quote the `QA-SOP.md`. If the answer isn't there, **update the SOP**.
3. **Delete with Confidence**: `ARCHIVE/` has a shelf life. If a file is >6 months old and unread, delete it. Bad info is worse than no info.
4. **Mine the Gold**: Every Retrospective MUST produce nuggets for `KNOWLEDGE-TREASURY.md`. Don't waste a painful lesson.

---

## 📁 Directory Structure

```
docs/qa/
├── README.md                      # This index
├── QA-DOCUMENTATION-AUDIT.md      # Cleanup audit record
│
├── STANDARDS/                     # 🔴 TIER 1: Master Standards
│   ├── QA-SOP.md                  # Master SOP (1200+ lines)
│   ├── TIERED-TESTING-GUIDE.md    # Testing methodology
│   ├── KNOWLEDGE-TREASURY.md      # Knowledge asset index
│   └── QA-STANDARDS-ALIGNMENT.md  # Alignment audit
│
├── TEMPLATES/                     # 🟡 TIER 2: Reusable Templates
│   └── CHECKLIST-TEMPLATE.md      # QA checklist template
│
├── REQUIREMENTS/                  # 🟢 Feature Requirements
│   ├── REQ-001-zygote-preload.md
│   ├── REQ-002-zygote-async.md
│   ├── REQ-003-bundle-config.md
│   └── REQ-004-security-hardening.md
│
├── DEFECTS/                       # 🔵 Defect Reports
│   └── (defect files)
│
├── PHASES/                        # 📚 Phase-Specific Records
│   ├── phase-1.5/
│   │   └── test-matrix.md
│   ├── phase-3/
│   │   ├── defect-report.md
│   │   ├── multi-agent-tests.md
│   │   └── test-matrix.md
│   ├── phase-3.5/
│   │   ├── defect-report.md
│   │   ├── multi-agent-tests.md
│   │   ├── test-gap-analysis.md
│   │   └── test-matrix.md
│   ├── phase-4/
│   │   ├── defect-report.md
│   │   ├── task-handoff-4.0.md
│   │   └── task-handoff-4.1.md
│   ├── phase-5/
│   │   ├── qa-framework.md
│   │   └── reviews/              # (18 review files)
│   └── phase-6/
│       ├── static-graph-verification.md
│       ├── multi-agent-tests-6.1.md
│       ├── qa-framework-6.1.md
│       ├── reviews-6.0/          # (18 review files)
│       └── reviews-6.1/
│
└── ARCHIVE/                       # 📦 Historical/Superseded
    ├── QA-AUDIT-RFC-0009.md
    ├── QA-INTEGRITY-REPORT-V2.md
    ├── QA-REFLECTION-FIRST-PRINCIPLES.md
    ├── SECURITY-BLUEPRINTS.md
    ├── arch-handover-2026-01-02.md
    ├── framework-battle-plan.md
    ├── arch/
    └── benchmarks/
```

---

## 📊 Statistics

| Category | Files | Description |
|:---|:---:|:---|
| STANDARDS | 4 | Master documents (1500+ lines) |
| TEMPLATES | 1 | Reusable templates |
| REQUIREMENTS | 4 | Feature specifications |
| DEFECTS | - | Defect reports |
| PHASES | 60+ | Phase-specific records |
| ARCHIVE | 8+ | Historical documents |
| **Total** | **~80** | **All QA documentation** |

---

## 📝 Naming Conventions

| Category | Format | Example |
|:---|:---|:---|
| **Standards** | `UPPER-CASE-HYPHEN.md` | `QA-SOP.md` |
| **Templates** | `UPPER-CASE-HYPHEN.md` | `CHECKLIST-TEMPLATE.md` |
| **Requirements** | `REQ-XXX-*.md` | `REQ-001-zygote-preload.md` |
| **Defects** | `DEF-XX-YYY-*.md` | `DEF-60-007-hash-mismatch.md` |
| **Phase Docs** | `lowercase-hyphen.md` | `test-matrix.md` |
| **Reviews** | `lowercase-hyphen.md` | `agent-a-edge-review.md` |

---

## 🔗 External References

| Document | Location |
|:---|:---|
| [Definition of Done](../DEFINITION_OF_DONE.md) | Project-wide quality gates |
| [Project Standards](../STANDARDS.md) | Naming conventions |
| [Test Architecture](../TEST_ARCHITECTURE.md) | Test environment guide |
| [Benchmark Suite](../../benchmark_projects.py) | Performance benchmarks |
| [Test Files](../../tests/qa/) | Pytest test suites |
| [RFC Documents](../rfcs/) | Feature specifications |

---

## 📋 How to Use

### For New QA Team Members
1. Read **[STANDARDS/QA-SOP.md](./STANDARDS/QA-SOP.md)** (1200+ lines)
2. Understand **[STANDARDS/TIERED-TESTING-GUIDE.md](./STANDARDS/TIERED-TESTING-GUIDE.md)**
3. Explore **[STANDARDS/KNOWLEDGE-TREASURY.md](./STANDARDS/KNOWLEDGE-TREASURY.md)**
4. Review recent PHASES for examples

### For Starting a New Phase
1. Create directory: `PHASES/phase-X.Y/`
2. Add `test-matrix.md`, `multi-agent-tests.md`
3. Create `reviews/` for expert reviews
4. Follow SOP workflow exactly

### For Reporting Defects
1. Create file: `DEFECTS/DEF-XX-YYY-short-name.md`
2. Use defect template from SOP
3. Update status as work progresses

---

## 🔄 Maintenance

| Task | Frequency | Owner |
|:---|:---|:---|
| Update SOP | Per Phase | QA Leader |
| Archive old docs | End of Phase | QA Team |
| Review alignment | Quarterly | QA Leader |
| Create phase directory | Start of Phase | QA Leader |

---

**Velo QA Working Group** | Library v2.0 | Reorganized 2026-01-04
