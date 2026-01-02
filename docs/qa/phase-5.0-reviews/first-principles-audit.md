# Phase 5.0 Fast Loader: First Principles Audit

> **Auditor**: QA Leader  
> **Methodology**: Start from zero, forget all preconceived assumptions  
> **Date**: 2026-01-03  
> **Core Principle**: "Tests passing ≠ Feature working"

---

## First Principles Review

From `QA_REFLECTION_first_principles.md`:

> **We tested the "shell", not the "core"**
> 
> If you only test system boundaries, not core functionality, test coverage is an illusion.

### Correct Testing Pyramid

```
           ▲
          /·\     Exploratory/Chaos (LAST)
         /···\    
        /─────\
       /·······\  Security
      /·········\ 
     /───────────\
    /·············\  Edge Cases
   /···············\ 
  /─────────────────\
 /···················\  SAD PATH
/·····················\ 
/───────────────────────\
/·························\  HAPPY PATH ← Must test FIRST!
/···························\ 
/─────────────────────────────\
```

---

# Part 1: Zero-Based Thinking - What is Fast Loader's Essence?

## Problem Definition

**What core problem does Fast Loader solve?**

From RFC-0006 Section 1.1:

> Python cold start is bottlenecked by:
> - sys.path search: ~10-50ms
> - File I/O (200 files): ~4-10ms
> - marshal parsing: ~1-2ms

**User expectation**: `velo run --fast main.py` is 5x faster than `python main.py`

---

## Level 0 (Smoke): Does it actually work?

### Critical Finding #1: RFC has no Level 0 test

Re-examining RFC-0006 Section 3 Implementation Plan:

```markdown
### Phase 5.0.1: Bundle Infrastructure (Week 1-2)
- [ ] Create `src/loader/` module
- [ ] Bundle format with rkyv
- [ ] Integrity verification
- [ ] Fallback mechanism
- [ ] Unit tests  ← What level are these tests?
```

**Problem**: What are "Unit tests"? Where is Level 0 smoke test defined?

**First principles requirement**:

```python
# LEVEL 0: This must exist and pass first
def test_smoke_fast_loader_works():
    """Does --fast flag actually make anything faster?"""
    # 1. Create a real project
    project = create_real_project_with_100_modules()
    
    # 2. Run without --fast
    time_normal = measure("velo run main.py")
    
    # 3. Run with --fast
    time_fast = measure("velo run --fast main.py")
    
    # 4. Is it actually faster?
    assert time_fast < time_normal, "Fast loader didn't make it faster!"
```

**If this test doesn't exist or doesn't pass, all other tests are meaningless.**

---

## Level 1 (Happy Path): Basic user journey

### Critical Finding #2: RFC describes mechanisms, not user journey

RFC describes in detail:
- Bundle format (Section 2.5)
- Import hook (Section 2.10)
- Verification (Section 2.11)

But **no complete user journey test**:

```python
# LEVEL 1: Complete user journey
def test_happy_path_full_journey():
    """Complete user journey from build to run"""
    project = create_fastapi_project()
    
    # Step 1: Build bundle (does this actually happen?)
    result = run("velo build")
    assert result.returncode == 0
    assert Path(".velo/cache/bundle.veloc").exists()
    
    # Step 2: First run (cold start)
    time_cold = measure("velo run --fast main.py")
    
    # Step 3: Second run (warm start)
    time_warm = measure("velo run --fast main.py")
    
    # Step 4: Import in code works
    # Not testing CLI args, but that import statements load from bundle
    assert "numpy" in loaded_from_bundle()
    
    # Step 5: Output correct
    response = requests.get("http://localhost:8000/")
    assert response.status_code == 200
```

---

## Level 2 (Sad Path): Failure scenarios

### Critical Finding #3: Does Fallback actually work?

RFC Section 2.10 says:

```python
class VeloFinder(MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name in self.bundle.index:
            return bundle_loader_spec(name)
        return None  # Fallback to normal import chain
```

**But no test verifies**:

```python
# LEVEL 2: Does Fallback actually work?
def test_fallback_actually_runs_code():
    """When bundle fails, code still executes correctly"""
    project = create_project()
    build_bundle()
    
    # Deliberately corrupt bundle
    corrupt_bundle()
    
    # Run code - must succeed (via fallback)
    result = run("velo run --fast main.py")
    assert result.returncode == 0  # Not checking logs, checking code runs
    
    # Output correct
    assert "Hello World" in result.stdout
```

---

# Part 2: What mistakes did our previous review make?

## Mistake #1: Over-focused on security boundaries, ignored core functionality

Previous review found 16 S0 security issues, but:

| We tested | We didn't test |
|-----------|----------------|
| Symlink bypass | Can bundle actually load modules? |
| Hash coverage | Is module execution correct? |
| Path check completeness | Is performance actually improved? |
| Integer overflow | Can user complete basic operations? |

**This is exactly the error QA_REFLECTION warned about: testing "shell" not "core"**

## Mistake #2: Assumed RFC design is viable

We defaulted to RFC mechanisms being correct, only checking for security holes.

**First principles questions**:

1. **Is `rkyv` actually faster than `serde`?** - RFC says use rkyv, but is there a benchmark?
2. **Does `memoryview` actually avoid copies?** - RFC says use memoryview, but was it measured?
3. **Is Import hook truly transparent?** - Could it break some libraries' import logic?

---

# Part 3: First Principles Test Matrix Restructure

## New Test Hierarchy

### Level 0: Smoke (Most basic validation)

| ID | Test | What it validates |
|----|------|-------------------|
| FP-L0-01 | `velo build` succeeds | Bundle can be created |
| FP-L0-02 | `bundle.veloc` exists | File actually generated |
| FP-L0-03 | `velo run --fast` succeeds | Program can run |
| FP-L0-04 | Program output correct | Functionality works |

### Level 1: Happy Path (Normal user journey)

| ID | Test | What it validates |
|----|------|-------------------|
| FP-L1-01 | Cold start faster than CPython | Performance goal met |
| FP-L1-02 | Warm start even faster | Cache effective |
| FP-L1-03 | 100-module project works | Scale support |
| FP-L1-04 | FastAPI project can start | Framework compatible |
| FP-L1-05 | Django project can start | Framework compatible |

### Level 2: Sad Path (Failure recovery)

| ID | Test | What it validates |
|----|------|-------------------|
| FP-L2-01 | Corrupted bundle -> Fallback | System still usable |
| FP-L2-02 | Fingerprint change -> Rebuild | Auto update |
| FP-L2-03 | Missing module -> Clear error | User knows what happened |

### Level 3: Config (Option validation)

| ID | Test | What it validates |
|----|------|-------------------|
| FP-L3-01 | `--rebuild` forces rebuild | Option works |
| FP-L3-02 | `--no-deps` only bundles project code | Option works |
| FP-L3-03 | `--exclude` excludes modules | Option works |

### Level 4: Security

**Only meaningful AFTER Levels 0-3 pass!**

| ID | Test | What it validates |
|----|------|-------------------|
| FP-L4-01 | Symlink attack blocked | Path security |
| FP-L4-02 | Corrupted bundle rejected | Integrity |
| FP-L4-03 | /tmp path rejected | Location security |

### Level 5: Edge/Chaos

**Only meaningful AFTER Levels 0-4 pass!**

| ID | Test | What it validates |
|----|------|-------------------|
| FP-L5-01 | 10000 modules | Scalability |
| FP-L5-02 | 256MB bundle | Boundary |
| FP-L5-03 | Unicode module name | Special chars |

---

# Part 4: RFC-0006 First Principles Questions

## Must answer before implementation

### Question 1: Is performance assumption validated?

RFC Section 0 says:

> Single read + slice = 5x faster than traditional

**Validation required**:
- [ ] Benchmark on real projects (FastAPI, Django)
- [ ] Results on different hardware (SSD vs HDD)
- [ ] Results on different Python versions

### Question 2: Is rkyv choice justified?

RFC Section 2.5 says use rkyv, but:
- [ ] Comparison benchmark with bincode?
- [ ] Comparison with msgpack?
- [ ] rkyv maturity in Python ecosystem?

### Question 3: Where are user journey tests?

RFC Section 3 only mentions "Unit tests", but:
- [ ] Who is responsible for E2E tests?
- [ ] When is user journey validated?
- [ ] What are acceptance criteria?

### Question 4: Are negative scenarios covered?

RFC Section 2.10 says "fallback to normal import", but:
- [ ] Does Fallback have E2E tests?
- [ ] What is Fallback performance penalty?
- [ ] How does user know fallback occurred?

---

# Part 5: Revised QA Strategy

## Old Strategy (Wrong)

```
1. Read RFC
2. Design security tests
3. Design edge tests
4. Cross-review
5. Find more security issues
```

## New Strategy (Correct)

```
1. Ask: "Does this thing actually work?"
2. Design Level 0 Smoke tests
3. After L0 passes, design Level 1 Happy Path
4. After L1 passes, design Level 2 Sad Path
5. Only after core functionality verified, test security/edge
```

---

# Part 6: Corrections to Previous Review

## Findings to Keep (Still valid)

The following security issues are still important, but priority should be lowered:

| Original ID | Issue | New Priority |
|-------------|-------|--------------|
| AUDIT-006 | content_hash coverage | P1 (Level 4) |
| AUDIT-011 | Symlink bypass | P1 (Level 4) |
| AUDIT-009 | Path check | P1 (Level 4) |

## New Findings (More Important)

| ID | Issue | Priority |
|----|-------|----------|
| **FP-CRITICAL-01** | No Level 0 Smoke test | **P0** |
| **FP-CRITICAL-02** | Performance assumption unvalidated | **P0** |
| **FP-CRITICAL-03** | User journey undefined | **P0** |
| **FP-CRITICAL-04** | Fallback has no E2E test | **P0** |

---

## First Principles Audit Conclusion

### Core Problem

**RFC-0006 describes in detail "how to implement", but not "how to verify it works".**

### Blocking Items

Before starting security tests, must first have:

1. **Level 0 Smoke test defined and passing**
2. **Level 1 Happy Path complete user journey**
3. **Real project Benchmark validating 5x performance improvement**

### Recommendations

1. Architect should add Section 3.6 Acceptance Criteria
2. QA should implement FP-L0/L1 tests first
3. Security/edge tests only after functionality verified

---

**QA Leader Sign-off**: First principles audit complete  
**Conclusion**: Our previous review direction was off, should return to functionality verification priority

---

**Document End**
