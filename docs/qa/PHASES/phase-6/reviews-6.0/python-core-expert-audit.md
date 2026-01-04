# RFC-0009 Python Core Expert Review

> **Reviewer Role**: 🐍 Python Import System Specialist  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟡 **CONDITIONAL APPROVAL** (Requires Clarifications on Import Semantics)

---

## Executive Summary

The RFC demonstrates a solid understanding of Python import overhead. However, the proposal underestimates several **Python-specific edge cases** that will cause correctness issues if not addressed. This review focuses on `importlib` protocol compliance and CPython behavioral parity.

---

## 🔴 Critical Findings (P0 - Must Fix)

### P0-001: `__path__` Mutation is Not Addressed

**Problem**: Python packages can dynamically modify `__path__` at runtime:

```python
# mypackage/__init__.py
import os
__path__.append(os.path.join(os.path.dirname(__file__), 'plugins'))
```

This allows packages to "discover" submodules from non-standard locations. A static graph built at compile-time will miss any modules added via `__path__` mutation.

**Risk Level**: 🔴 **CRITICAL** - Django, Flask, and many plugin systems rely on this.

**Recommendation**:
1. The static graph MUST NOT override `__path__` behavior.
2. If a module is a package AND its `__path__` is mutated, all subsequent submodule lookups MUST fall back to standard import.
3. Add a `mutable_path_packages: Set<String>` field to the graph to track packages with known `__path__` mutations.

---

### P0-002: `__import__` Hook Interception

**Problem**: Some frameworks override `builtins.__import__`:

```python
import builtins
_original_import = builtins.__import__

def custom_import(name, *args, **kwargs):
    print(f"Importing: {name}")
    return _original_import(name, *args, **kwargs)

builtins.__import__ = custom_import
```

If Velo's graph bypasses `__import__`, these hooks will be silently ignored.

**Risk Level**: 🔴 **CRITICAL** - Testing frameworks (pytest, unittest.mock) and debugging tools rely on this.

**Recommendation**:
1. Velo MUST NOT bypass `builtins.__import__`.
2. The graph should only accelerate the **module finding** phase (`MetaPathFinder.find_spec`), not the actual import execution.
3. Ensure all imports still flow through the standard `importlib.import_module()` path.

---

## 🟡 Design Gaps (P1 - Must Fix Before Implementation)

### P1-005: Namespace Packages (PEP 420) Handling

**Problem**: Namespace packages have no `__init__.py` and can span multiple directories:

```
/path1/mypkg/subA/
/path2/mypkg/subB/
```

Both contribute to the `mypkg` namespace. Static analysis of a single project directory will miss contributions from other `sys.path` entries.

**Recommendation**:
1. Document that namespace packages spanning multiple source roots are NOT fully supported.
2. For single-root namespace packages, detect the absence of `__init__.py` and mark as `is_namespace: true` in the graph.

---

### P1-006: Lazy Imports (PEP 690) Compatibility

**Problem**: Python 3.12+ supports lazy imports via `PYTHONDEBUG=L`. The static graph assumes eager import, which conflicts with lazy semantics.

**Recommendation**:
1. Detect if `PYTHONDEBUG=L` or `sys.flags.lazy_imports` is set.
2. If lazy imports are enabled, disable graph-based preloading but still use the graph for `find_spec` acceleration.

---

### P1-007: `__spec__.submodule_search_locations` Correctness

**Problem**: When returning a `ModuleSpec` for a package, the `submodule_search_locations` attribute MUST be set correctly for submodule discovery to work.

**Current RFC Gap**: Section 4.2 does not specify how `submodule_search_locations` is populated from the graph.

**Recommendation**:
1. Store `search_locations: Vec<String>` in the graph for each package.
2. When constructing `ModuleSpec`, populate `submodule_search_locations` from the cached value.

---

## 🟠 Design Considerations (P2 - Should Address)

### P2-004: `importlib.metadata` Integration

**Problem**: `importlib.metadata.version("package")` and `importlib.resources` use a separate resolution path that won't benefit from the static graph.

**Recommendation**: Document this as a known limitation. Consider Phase 6.3 for metadata graph integration.

---

### P2-005: Relative Import Edge Cases

**Problem**: Relative imports (`from . import foo`) depend on `__package__` being set correctly. If the graph is consulted before `__package__` is established, resolution will fail.

**Recommendation**: Ensure `__package__` is set on the module object BEFORE graph lookup for any relative import.

---

### P2-006: `sys.modules` Consistency

**Problem**: Python requires that after a successful import, `sys.modules[name]` contains the module. If the graph is used to skip finding but something goes wrong during execution, `sys.modules` state may be inconsistent.

**Recommendation**:
1. The loader MUST add the module to `sys.modules` BEFORE `exec_module()` is called (this is standard importlib protocol).
2. On `exec_module()` failure, the module MUST be removed from `sys.modules`.

---

## ✅ Strengths Acknowledged

| ID | Finding |
|----|---------|
| S-05 | Correct use of `MetaPathFinder` interface |
| S-06 | Fallback to standard import for unknown modules |
| S-07 | BLAKE3 hash for graph integrity (H-8) |
| S-08 | Tarjan's SCC for circular import handling |

---

## 📋 Required Actions Before Approval

1. **[P0-001]** Add specification for `__path__` mutation handling.
2. **[P0-002]** Clarify that all imports still flow through `builtins.__import__`.
3. **[P1-005]** Document namespace package limitations.
4. **[P1-006]** Add lazy import (PEP 690) compatibility check.
5. **[P1-007]** Specify `submodule_search_locations` handling in graph schema.

Once these are addressed, RFC-0009 is **approved for implementation**.

---

*Reviewed by: 🐍 Python Core Expert (Simulated CPython Contributor)*  
*Review Protocol: Python Import System Compliance Check*
