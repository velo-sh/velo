# Velo Project Standards

Unified naming and organizational conventions for consistent future development.

---

## 1. Directory Structure

```
velo/
├── .github/
│   └── workflows/
│       ├── ci.yml              # Main CI pipeline
│       └── release.yml         # Release pipeline (future)
├── docs/
│   ├── DEFINITION_OF_DONE.md   # Quality gate standards
│   ├── STANDARDS.md            # This document
│   ├── rfcs/                   # RFC design documents
│   │   ├── README.md
│   │   └── 0001-phase-1.5-env-detection.md
│   ├── qa/                     # QA documentation
│   │   ├── README.md
│   │   ├── QA_CHECKLIST_TEMPLATE.md
│   │   └── phase-1.5-test-matrix.md
│   └── testing/                # Testing guides
│       └── phase-1.5-qa-guide.md
├── scripts/
│   ├── setup-dev.sh            # Dev environment setup
│   ├── test-phase{X.Y}.sh      # Dev acceptance tests
│   └── ci-qa.sh                # QA CI test runner
├── src/                        # Rust source code
├── tests/
│   ├── corpus/                 # Test Python scripts
│   └── qa/                     # QA adversarial tests (pytest)
│       ├── conftest.py
│       ├── test_harness.py
│       └── test_*.py
└── target/                     # Cargo build artifacts
```

---

## 2. Naming Conventions

### 2.1 Documentation

| Type | Format | Example |
|------|--------|---------|
| RFC | `NNNN-<kebab-case>.md` | `0001-phase-1.5-env-detection.md` |
| QA Test Matrix | `phase-{X.Y}-test-matrix.md` | `phase-1.5-test-matrix.md` |
| QA Guide | `phase-{X.Y}-qa-guide.md` | `phase-1.5-qa-guide.md` |
| Defect Report | `phase-{X.Y}-defect-report.md` | `phase-1.5-defect-report.md` |

### 2.2 Scripts

| Type | Format | Example |
|------|--------|---------|
| Dev Acceptance | `test-phase{X.Y}.sh` | `test-phase1.5.sh` |
| CI Runner | `ci-{scope}.sh` | `ci-qa.sh` |
| Setup Script | `setup-{purpose}.sh` | `setup-dev.sh` |

### 2.3 Test Files (Python)

| Type | Format | Example |
|------|--------|---------|
| Phase Feature Tests | `test_phase{X_Y}_features.py` | `test_phase1_5_features.py` |
| Category Tests | `test_{category}.py` | `test_chaos_cache.py` |
| Shared Infrastructure | `test_harness.py` | - |

### 2.4 CI Job Names

| Type | Format | Example |
|------|--------|---------|
| Build & Test | `build` | Build & Test |
| Code Quality | `{tool}` | `clippy`, `fmt` |
| QA Tests | `qa-tests` | QA Adversarial Tests |
| Release | `release` | Release |

---

## 3. Test Categories

### 3.1 Test ID Prefixes

| Prefix | Category | Description |
|--------|----------|-------------|
| `CHAOS-` | Chaos Tests | Corruption, race conditions, resource exhaustion |
| `PYDET-` | Python Detection | Fake Python, symlink loops |
| `FUZZ-` | Input Fuzzing | Malicious input, special characters |
| `ENV-` | Environment Pollution | Environment variables, permissions |
| `FP-` | Fingerprint Attacks | uv.lock manipulation |
| `RACE-` | Concurrency Tests | Race conditions |
| `ABI-` | ABI Compatibility | Python version switching |
| `PRF-` | Profiling | --profile related |
| `INF-` | System Info | velo info related |

### 3.2 Test Class Naming

```python
# Format: Test{Category}{SubCategory}
class TestCacheChaosCORRUPTION:  # Cache category, Corruption subcategory
class TestPythonDetectionFAKE:   # Python detection, Fake subcategory
class TestVeloInfo:              # Feature tests
class TestProfile:               # Feature tests
```

---

## 4. Version and Phase Naming

| Phase | Version | Codename | Description |
|-------|---------|----------|-------------|
| 1 | v0.1.x | Tachyon | Basic path caching |
| 1.5 | v0.2.x | - | Environment detection enhancement |
| 2 | v0.3.x | Supervisor | Process isolation |
| 3 | v0.4.x | Zygote | Process pre-warming |
| 4 | v0.5.x | - | Static analysis |

---

## 5. Commit Convention

```
<type>: <description>

[optional body]
```

| Type | Usage |
|------|-------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation update |
| `test` | Test addition/modification |
| `ci` | CI configuration |
| `chore` | Miscellaneous maintenance |
| `refactor` | Code refactoring |

---

## 6. CI Pipeline Structure

```yaml
# Parallel execution
┌─────────┐  ┌─────────┐  ┌─────────┐
│  build  │  │ clippy  │  │   fmt   │
└────┬────┘  └─────────┘  └─────────┘
     │
     ▼ (depends)
┌──────────┐
│ qa-tests │
└──────────┘
```

---

## 7. QA Workflow

```
1. Dev submits PR
2. CI runs automatically:
   - cargo test (unit tests)
   - clippy (code quality)
   - fmt (format check)
   - qa-tests (adversarial tests)
3. QA manual verification:
   - Fill out QA_CHECKLIST_TEMPLATE.md
   - Add adversarial tests
4. Sign-off for release
```

---

**Last Updated**: 2026-01-01
