# DEF-60-002: L0-1 AST Dependency Classification Failure

**Status**: FAILED (Persistent after fix `2b635e9`)
**Severity**: P1 (Logic Defect)
**Component**: `src/graph/dependency.rs` (DependencyScanner)

## 1. Reproduction Command
Run this specific test case from the project root:

```bash
uv run pytest tests/qa/test_phase6_agent_a_edge.py::TestAgentAEdge::test_L0_1_ast_dependency_classification -vv
```

## 2. Test Case Logic (Simplified)
The test creates a `main.py` with different import types (Hard vs Soft) and expects the scanner to distinguish them.

```python
# main.py
import hard_mod          # Hard Dependency (Must be eager loaded)
if False: import soft_if  # Soft Dependency (Should be skipped or lazy)
try: import soft_try; except: pass # Soft Dependency (Should be skipped or lazy)
def f(): import soft_fn  # Soft Dependency (Should be skipped or lazy)
```

**Failure Mode**: 
The scanner currently classifies `soft_fn` (inside function) or `soft_try` as generic imports (likely "Hard"), causing incorrect graph edges or pre-loading behavior.

## 3. Expected Behavior (RFC-0009)
- Top-level `import x` -> **Hard Dependency** (Edge in Static Graph)
- Inside `def/class` or `try/except` -> **Soft/Conditional** (Should NOT be a Hard Edge in Static Graph, or marked `is_dynamic=true`)

## 4. Current Output
The test fails because the build/graph generation logic does not correctly utilize the AST metadata to differentiate these imports.
