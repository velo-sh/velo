# QA Supplement Plan: Architect Updates 2026-01-03

> **RFC**: 0006 Phase 5.0.2 Fast Loader  
> **Changes**: velo_loader.py, bundle_builder.py, bundle.rs, run.rs  
> **Architect Tests**: 13 tests in test_phase5_loader.py

---

## 1. Architect Implementation Summary

| File | Lines | Components |
|------|-------|------------|
| `python/velo_loader.py` | 377 | VeloBundle, VeloFinder, VeloLoader |
| `python/bundle_builder.py` | 192 | VeloBundleBuilder, build_from_project |
| `src/cmd/bundle.rs` | 308 | bundle inspect, verify_bundle |
| `src/cmd/run.rs` | 345 | --fast flag, sitecustomize injection |

---

## 2. Architect Test Coverage Analysis

### Existing Tests (test_phase5_loader.py - 13 tests)

| Class | Test | Coverage |
|-------|------|----------|
| TestVeloBundleBuilder | test_build_simple_module | ✅ Builder basic |
| TestVeloBundleBuilder | test_build_from_source | ✅ Source compile |
| TestVeloBundleBuilder | test_build_from_project | ✅ Project build |
| TestVeloBundle | test_open_bundle | ✅ Open/close |
| TestVeloBundle | test_get_code | ✅ Get bytecode |
| TestVeloBundle | test_reject_oversized_bundle | ⚠️ Only constant check |
| TestVeloBundle | test_fallback_for_missing_module | ✅ Fallback |
| TestVeloFinder | test_find_spec_for_bundled_module | ✅ Import hook |
| TestVeloFinder | test_find_spec_returns_none_for_missing | ✅ Fallback |
| TestVeloFinder | test_import_from_bundle | ✅ Real import |
| TestVeloLoader | test_exec_module_verifies_hash | ✅ BLAKE3 verify |
| TestIntegration | test_full_workflow | ✅ E2E |

---

## 3. QA Gaps Identified

### Missing Security Tests (from RFC §3)

| Gap | RFC Section | Priority |
|-----|-------------|----------|
| Bundle size >256MB rejection | §3.1 | P0 |
| Bundle corruption detection | §3.4 | P0 |
| Module hash tampering | §3.4 | P1 |
| Invalid magic rejection | - | P1 |
| Invalid version rejection | - | P1 |

### Missing CLI Tests

| Gap | Command | Priority |
|-----|---------|----------|
| `velo bundle inspect` | bundle.rs | P1 |
| `velo bundle inspect --verify` | bundle.rs | P1 |
| `velo run --fast` fallback | run.rs | P0 |
| `velo run --fast` success | run.rs | P0 |

### Missing Edge Case Tests

| Gap | Scenario | Priority |
|-----|----------|----------|
| Empty bundle (0 modules) | - | P2 |
| Package with __path__ | VeloLoader | P1 |
| Fallback to stdlib | VeloFinder | P1 |

---

## 4. Proposed QA Supplement Tests

### A. Security Tests (to add in test_l4_security.py)

```python
# 1. test_bundle_size_limit
# 2. test_bundle_invalid_magic
# 3. test_bundle_invalid_version
# 4. test_module_hash_tampering
```

### B. CLI Tests (new file: test_cli_bundle.py)

```python
# 1. test_bundle_inspect_basic
# 2. test_bundle_inspect_verify
# 3. test_bundle_inspect_modules
# 4. test_bundle_inspect_json
# 5. test_run_fast_with_bundle
# 6. test_run_fast_without_bundle_fallback
```

### C. Integration Tests (to add in tests/qa/phase5/)

```python
# 1. test_package_path_support
# 2. test_stdlib_fallback
# 3. test_empty_bundle_handling
```

---

## 5. Verification Plan

### Run Architect's Tests

```bash
pytest tests/qa/test_phase5_loader.py -v
```

### Run QA Supplement Tests

```bash
pytest tests/qa/phase5/ -v
```

### Run Full Suite

```bash
pytest tests/qa/ -v --tb=short
```

---

## 6. Files to Create/Modify

| Action | File | Tests |
|--------|------|-------|
| CREATE | tests/qa/phase5/test_cli_bundle.py | 6 tests |
| MODIFY | tests/qa/phase5/test_l4_security.py | +4 tests |
| MODIFY | tests/qa/phase5/test_l0_smoke.py | Update for new impl |

---

**Estimated effort**: 10 test cases
