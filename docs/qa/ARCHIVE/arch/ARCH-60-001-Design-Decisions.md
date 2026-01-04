# ARCH-60-001: Design Decisions Required

**Status**: PENDING ARCHITECT REVIEW
**Reporter**: QA Working Group
**Date**: 2026-01-03

## Summary
The following test cases have been marked as `xfail` because they represent **design-intentional limitations** rather than bugs. QA requests Architecture Team confirmation that these are the intended behaviors.

---

## 1. EDGE-603: Symlink Target Change Detection

**Current Behavior**: 
- Bundle is built with symlink `link.py → target_a.py`
- Symlink target changes to `link.py → target_b.py`
- `velo run --fast` still loads the original `target_a.py` content

**Question for Architect**:
Is this the intended behavior? Should bundles invalidate when source symlinks change?

**Options**:
1. ✅ **Accept as Design** - Bundle is a compile-time snapshot
2. ⚠️ **Add Warning** - Detect symlink mtime and warn user to rebuild
3. 🔄 **Auto-Rebuild** - Check symlink targets at load time

---

## 2. FUNC-601: `__path__` Mutation at Runtime

**Current Behavior**:
- Django-style packages mutate `__path__` at import time
- Static graph cannot predict these runtime mutations
- Submodules in mutated paths fail to load

**Question for Architect**:
Is CPython fallback the correct strategy for these cases?

**Options**:
1. ✅ **Accept CPython Fallback** - Documented limitation
2. 📝 **Instrumented Fallback** - Log when fallback occurs for user awareness
3. 🔬 **Dynamic Hint** - Allow `pyproject.toml` hints for known mutators

---

## 3. L5 Metrics: Missing `fallback_reasons` Field

**Current Behavior**:
- RFC-0009 specifies `fallback_reasons` in Metrics JSON
- Current implementation omits this field

**Question for Architect**:
Should this be P2 (must implement) or P3 (nice to have)?

**RFC Reference**: Section 5.3 Observability Requirements

---

## 4. EDGE-604: Hard Limit Now Configurable

**Current Behavior**:
- 5,000 module hard limit was previously a build failure
- Now configurable, builds with 5,001+ modules succeed

**Question for Architect**:
Please confirm this is the intended design change and update RFC-0009 if needed.

---

**QA Action**: Tests marked as `xfail` pending architecture decision.
**Next Step**: Architect to respond with YES/NO/DEFER for each item.

---
**QA Signature**: Velo QA Working Group
