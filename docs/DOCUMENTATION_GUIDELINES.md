# Documentation Guidelines

> **Version**: v1.0  
> **Updated**: 2026-01-02

---

## Directory Structure

```
docs/
├── STANDARDS.md              # Project standards
├── DEFINITION_OF_DONE.md     # Quality gates
├── DOCUMENTATION_GUIDELINES.md # This file
│
├── rfcs/                     # Design documents (permanent)
│   ├── README.md
│   ├── 0001-xxx.md
│   └── ...
│
├── qa/                       # QA documents (current phase only)
│   ├── README.md
│   ├── test-matrix.md
│   └── ...
│
├── roadmap/                  # Roadmaps (by quarter)
│   └── 2026-H1.md
│
└── archive/                  # Archived documents
    └── phase-x.x/
```

---

## Document Types & Lifecycle

| Type | Location | Lifecycle | Owner |
|------|----------|-----------|-------|
| RFC | `docs/rfcs/` | Permanent | Architect |
| Test Matrix | `docs/qa/` | Per-phase update | QA |
| Defect Report | **GitHub Issues** | Close when fixed | QA |
| Roadmap | `docs/roadmap/` | Quarterly | Architect |

---

## Bug Management

### Use GitHub Issues (Recommended)

```bash
# DO NOT create docs/qa/DEF-xxx.md
# Use GitHub Issues instead
```

**Issue Template**:
```markdown
## Bug Summary
[Short description]

## Steps to Reproduce
1. ...
2. ...

## Expected vs Actual
- Expected: ...
- Actual: ...

## Environment
- OS: macOS/Linux
- Velo version: v0.3.0

## Labels
bug, priority:high, phase:3.5
```

### Issue Naming Convention

```
[BUG] DEF-xxx: Short description
[FEAT] Feature description
[DOCS] Documentation update
```

---

## RFC Standards

### File Naming
```
0001-phase-x-feature-name.md
```

### Status Flow
```
Draft → RFC → Approved → Implemented
```

### Required Sections
1. Executive Summary
2. Technical Design
3. Implementation Plan
4. Success Metrics

---

## QA Document Standards

### Per Phase, Keep Only:
1. `test-matrix.md` - Test cases
2. Defects tracked in GitHub Issues

### After Phase Release:
1. Close all related Issues
2. Update `docs/qa/README.md`
3. Archive old documents to `archive/`

---

## Privacy & Security Compliance

> **The "No Leakage" Rule (TITANIUM Standard)**

Every document created or modified MUST pass the following audit:

1. **No Absolute Paths**: Forbid `file:///Users/username/...`. Use relative links or `${PLACEHOLDERS}`.
2. **No Usernames**: Ensure no local system usernames (e.g., `gjwang`) are present.
3. **No Secrets**: Zero hardcoded keys, tokens, or passwords.
4. **No Environment Leakage**: Use `${HOME}`, `${CWD}`, or `${VIRTUAL_ENV}` instead of actual resolved paths.

**Audit Failure = P0 Blocker**.

---

## Archive Process

After each phase release:

```bash
# 1. Create archive directory
mkdir -p docs/archive/phase-3.0

# 2. Move outdated documents
mv docs/qa/phase-3-defect-report.md docs/archive/phase-3.0/

# 3. Update archive index
# docs/archive/README.md
```

---

## Checklist

**Dev Pre-Commit:**
- [ ] RFC status updated
- [ ] Changelog updated
- [ ] **Privacy Audit**: No local absolute paths or usernames?
- [ ] Tests passing

**QA Sign-Off:**
- [ ] Defects closed (GitHub Issues)
- [ ] Test Matrix updated
- [ ] Old documents archived

---

**Document End**
