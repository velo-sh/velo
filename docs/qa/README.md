# Velo QA Documentation

This directory contains QA testing documentation for Velo.

---

## 📋 Standards

| Document | Description |
|----------|-------------|
| [**tiered-testing-guide.md**](./tiered-testing-guide.md) | **Official QA Standards** - Tiered testing, CI integration |
| [QA_CHECKLIST_TEMPLATE.md](./QA_CHECKLIST_TEMPLATE.md) | Manual QA checklist template |
| [QA_REFLECTION_first_principles.md](./QA_REFLECTION_first_principles.md) | Testing lessons learned |

---

## 🧪 Quick Start

```bash
# Smoke tests (3s) - Always run first!
./scripts/qa-fast.sh 0

# Fast tests (15s) - Security & error handling
./scripts/qa-fast.sh 1

# Full suite (7min) - Before merge
./scripts/qa-fast.sh 2
```

---

## 📊 Test Matrices by Phase

| Phase | Test Matrix | Defect Report | Multi-Agent Tests |
|-------|-------------|---------------|-------------------|
| 1.5 | [phase-1.5-test-matrix.md](./phase-1.5-test-matrix.md) | - | - |
| 3 | [phase-3-test-matrix.md](./phase-3-test-matrix.md) | [phase-3-defect-report.md](./phase-3-defect-report.md) | [phase-3-multi-agent-tests.md](./phase-3-multi-agent-tests.md) |
| 3.5 | [phase-3.5-test-matrix.md](./phase-3.5-test-matrix.md) | [phase-3.5-defect-report.md](./phase-3.5-defect-report.md) | [phase-3.5-multi-agent-tests.md](./phase-3.5-multi-agent-tests.md) |

---

## 📁 Supporting Documents

| Document | Purpose |
|----------|---------|
| [phase-3.5-test-gap-analysis.md](./phase-3.5-test-gap-analysis.md) | Gap analysis from first principles review |
| [DEF-003-zygote-prewarm.md](./DEF-003-zygote-prewarm.md) | Zygote prewarm defect analysis |

---

## 🔗 Related

- [../TEST_ARCHITECTURE.md](../TEST_ARCHITECTURE.md) - **Test environment isolation (MUST READ)**
- [../STANDARDS.md](../STANDARDS.md) - Project naming conventions
- [../DEFINITION_OF_DONE.md](../DEFINITION_OF_DONE.md) - Quality gate standards
