# Agent A Findings (Edge & Compliance)

**Phase**: 6.1
**Agent**: Agent A (Edge)
**Date**: 2026-01-04

---

## Finding: EDGE-61-001

**Severity:** P1
**Category:** Bug
**Description:** `detect_app.py` did not recognize Django apps using `get_wsgi_application()` factory function.
**Evidence:** 
```bash
uv run pytest tests/qa/test_detect_app_compliance.py -v
# test_django_application FAILED (KeyError: 'app')
```
**Recommendation:** Add `get_wsgi_application` and `get_asgi_application` to `FRAMEWORK_PATTERNS`.
**Status:** **FIXED & VERIFIED** (DEF-61-001)

---

## Finding: EDGE-61-002

**Severity:** P3
**Category:** Enhancement
**Description:** Consider adding support for Quart (async Flask) framework detection.
**Evidence:** N/A
**Recommendation:** Add `("Quart", "Quart")` to FRAMEWORK_PATTERNS (already present).
**Status:** **NO ACTION REQUIRED**

---

**Agent A Summary**: 1 P1 found and fixed. No outstanding issues.
