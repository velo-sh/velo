# Grand Council Review: RFC-0038-ext Code Context Snippets

> **Review Date**: 2026-01-23  
> **Document**: [RFC-0038-ext: Code Context Snippets](../0038-ext-code-snippets.md)  
> **Authority**: SOP-001 TITANIUM Standard

---

## 📜 Phase I: Council Composition

### Selected Reviewers

| Role | Rationale |
|:---|:---|
| **Rust Core Dev** | New `snippet_extractor.rs` module, `rustpython_parser` usage |
| **Python Core Dev** | Import hook modification, `__file__` access semantics |
| **HPC Engineer** | Performance budget critical (100ms target, rayon parallelism) |
| **Architect** | Cross-cutting feature touching profile.rs, diagnostics.rs |
| **Security Engineer** | File system access, path traversal risks |

---

## 🗣️ Phase II: Council Critique

### Agent A: Rust Core Dev 🦀

> **Focus**: Systems Safety, `unsafe` blocks, Memory Model

**Questions Raised**:

1. **P0 QUESTION**: The proposed `extract_snippets_parallel` uses `rayon::par_iter()`. What happens if parsing panics? Does this crash the entire Velo process?
   
   ```rust
   imports.par_iter()
       .take(5)
       .map(|i| extract_module_entry_snippet(...))  // Panic here?
       .collect()
   ```
   
   **RECOMMENDATION**: Wrap with `catch_unwind` or use `par_iter().map(|i| std::panic::catch_unwind(...))`.

2. **P1 QUESTION**: The code reads arbitrary file paths from Python runtime:
   ```rust
   let source = std::fs::read_to_string(file_path).ok()?;
   ```
   Is there a size limit? A malicious module could point to `/dev/urandom` or a 10GB file.
   
   **RECOMMENDATION**: Add file size check (e.g., max 1MB).

3. **P2 OBSERVATION**: `rustpython_parser` performance varies with Python version syntax. Have you tested with Python 3.12+ pattern matching?

**Verdict**: ⚠️ **CONDITIONAL APPROVAL** (Fix P0 panic handling)

---

### Agent B: Python Core Dev 🐍

> **Focus**: Runtime Internals, GIL, Refcounting

**Questions Raised**:

1. **P0 QUESTION**: The hook captures `module.__file__` after import:
   ```python
   module = _velo_original_import(name, *args, **kwargs)
   file_path = getattr(module, '__file__', None)
   ```
   
   For **namespace packages**, `__file__` is `None`. For **frozen modules** (like `_frozen_importlib`), it may be `<frozen>`. Is this handled?
   
   **RECOMMENDATION**: Add namespace package and frozen module detection.

2. **P1 QUESTION**: Is `getattr(module, '__package__', None)` necessary in the hook? The architecture doesn't show how `__package__` is used.
   
   **RECOMMENDATION**: Remove unused data capture or document usage.

3. **P1 OBSERVATION**: The 1.0ms threshold is arbitrary:
   ```python
   if elapsed > 1.0:  # Only for slow imports
   ```
   Should be configurable via environment variable.

**Verdict**: ⚠️ **CONDITIONAL APPROVAL** (Address namespace packages)

---

### Agent C: HPC Engineer ⚡

> **Focus**: Hot Path, Allocations, Parallelism

**Questions Raised**:

1. **P0 QUESTION**: The performance budget claims "<100ms for Top 5":
   | Operation | Claimed | Actual (measured?) |
   |:---|:---|:---|
   | Parse AST | 5-20ms | **Not verified** |
   
   **RECOMMENDATION**: Add benchmark before merging. Use `criterion` crate.

2. **P1 QUESTION**: `rayon` parallelism with 5 items may have thread spawn overhead > benefit. For <5 items, serial may be faster.
   
   **RECOMMENDATION**: Add threshold: `if imports.len() > 3 { parallel } else { serial }`.

3. **P2 OBSERVATION**: Memory budget claims "<10MB" but `rustpython_parser` can allocate significantly more for complex files. Consider fallback to skip if memory pressure.

**Verdict**: ⚠️ **CONDITIONAL APPROVAL** (Add benchmarks before v1.0)

---

### Agent D: Architect 🏛️

> **Focus**: Coherence, 5-year Vision, API Stability

**Questions Raised**:

1. **P1 QUESTION**: The `CodeSnippet` struct is introduced as part of public API:
   ```rust
   pub struct CodeSnippet { ... }
   ```
   Is this part of the **Stable Public Protocol** (RFC-0038 §1.0)? If so, changing it will be a breaking change.
   
   **RECOMMENDATION**: Mark as `#[non_exhaustive]` or document as internal.

2. **P1 OBSERVATION**: The architecture shows a new file `src/common/snippet_extractor.rs`. This should be `src/diagnostic/snippet.rs` to match existing module organization.

3. **P2 QUESTION**: Future consideration mentions "py-spy integration". This is a significant scope creep. Recommend keeping out of this RFC.

**Verdict**: ✅ **APPROVED** (with P1 naming recommendations)

---

### Agent E: Security Engineer 🔐

> **Focus**: Attack Surface, Path Traversal, Data Leakage

**Questions Raised**:

1. **P0 QUESTION**: File paths come from Python runtime via `module.__file__`. A malicious package could set:
   ```python
   __file__ = "/etc/passwd"
   ```
   Would Velo include `/etc/passwd` contents in diagnostic report?
   
   **RECOMMENDATION**: Validate file path is within known site-packages or venv directory. Reject absolute paths outside sandbox.

2. **P0 QUESTION**: Code snippets may contain **secrets** if a developer hardcodes them:
   ```python
   API_KEY = "sk-12345..."  # Would be exposed in report!
   ```
   
   **RECOMMENDATION**: Apply existing `sanitize_env` pattern to code snippets. Scan for `KEY`, `SECRET`, `PASSWORD` patterns.

3. **P1 OBSERVATION**: The graceful degradation for `.so` files is good. Consider adding `.dll` for Windows.

**Verdict**: ❌ **REQUEST CHANGES** (P0 security issues must be addressed)

---

## 📝 Phase III: The Verdict

### Summary

| Reviewer | Verdict | Blocking Issues |
|:---|:---:|:---|
| Rust Core Dev | ⚠️ Conditional | P0: Panic handling in rayon |
| Python Core Dev | ⚠️ Conditional | P0: Namespace package handling |
| HPC Engineer | ⚠️ Conditional | P0: Need benchmarks |
| Architect | ✅ Approved | — |
| Security Engineer | ❌ Request Changes | P0: Path traversal, secret exposure |

---

## 🚨 P0 Blocking Issues

The following **MUST** be addressed before implementation:

1. **SEC-001: Path Traversal Defense**
   - Validate `__file__` is within expected directories (site-packages, venv, project)
   - Reject absolute paths to sensitive system files

2. **SEC-002: Secret Sanitization in Snippets**
   - Apply regex filter to code snippets for `KEY`, `SECRET`, `TOKEN`, `PASSWORD`
   - Redact matching lines with `# [REDACTED]`

3. **PANIC-001: Rayon Error Handling**
   - Wrap parallel parsing with `catch_unwind`
   - Return `None` for panicking modules instead of crashing

4. **COMPAT-001: Namespace Package Support**
   - Handle `__file__ = None` gracefully
   - Skip snippet extraction for frozen modules

---

## ✅ Final Verdict

### ❌ REQUEST CHANGES

The RFC extension architecture is well-structured but has **4 P0 blocking issues** that must be addressed in the document before implementation begins.

**Required Updates**:
1. Add **Security Considerations** section (§9) addressing SEC-001, SEC-002
2. Add **Error Handling** section (§10) for PANIC-001
3. Update Phase 1 hook code to handle namespace packages (COMPAT-001)
4. Add note about benchmarking requirement before merge

---

**Review Board Signature**: Grand Council (5 Experts)  
**Date**: 2026-01-23
