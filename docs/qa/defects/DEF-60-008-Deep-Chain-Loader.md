# DEF-60-008: Deep Dependency Chain Loader Failure

**Priority**: P2
**Status**: OPEN
**Reporter**: QA Working Group
**Assignee**: Developer

## Summary
Fast Loader crashes when executing deep dependency chains (10+ levels of nested imports).

## Reproduction

```bash
uv run pytest tests/qa/test_phase6_agent_a_edge.py::TestAgentAEdge::test_EDGE_601_deep_dependency_dag[10] -v
```

## Test Code
```python
# Create chain: m0 → m1 → m2 → ... → m9
for i in range(10):
    if i == 9:
        env.create_app(f"m{i}.py", f"# Leaf module")
    else:
        env.create_app(f"m{i}.py", f"import m{i+1}")

env.create_app("main.py", "import m0; print('CHAIN_DEPTH_10')")
```

## Expected Behavior
- `velo bundle build` succeeds
- `velo run --fast main.py` prints `CHAIN_DEPTH_10`

## Actual Behavior
```
AttributeError: module 'm9' has no attribute 'm9'
```

The loader fails to correctly execute the module chain, causing attribute errors.

## Root Cause Analysis
The `velo_loader.py` `exec_module` function appears to have issues with:
1. Recursive module execution order
2. Module attribute initialization timing

## Impact
- Edge case affecting very deep import chains
- Most real projects unlikely to exceed 10 levels
- Django/Flask/FastAPI E2E tests all pass (no impact on typical usage)

## Suggested Fix
Review `exec_module` in `python/velo_loader.py` for proper module initialization order during chain loading.

---
**QA Signature**: Velo QA Working Group
