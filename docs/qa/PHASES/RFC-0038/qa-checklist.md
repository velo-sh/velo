# RFC-0038 QA Checklist

> **Phase**: RFC-0038 AI-Native Diagnostics
> **Target Version**: v0.9.5
> **Date**: 2026-01-23
> **Priority**: P0 (Strategic)

---

## 📋 Pre-Implementation Checklist (Phase 0)

### Architecture Alignment
- [x] RFC-0038 document read and understood
- [x] Developer Handoff Ticket reviewed
- [x] All MUST requirements extracted (11 items)
- [x] All security invariants identified (7 items)
- [x] Performance thresholds documented (<5% overhead)
- [x] Test matrix created
- [x] Requirements traceability established

### Documentation
- [x] `architecture-alignment.md` created
- [x] `test-matrix.md` created
- [x] `REQUIREMENTS_TRACEABILITY.md` created
- [x] `qa-checklist.md` created (this file)
- [ ] Agent review templates prepared

---

## 🔧 Implementation Verification Checklist

### New Files
- [ ] `src/common/diagnostics.rs` exists
- [ ] `MarkdownFormatter` struct implemented
- [ ] Secrets sanitizer filter implemented
- [ ] ANSI strip functionality implemented

### Modified Files
- [ ] `src/cmd/run.rs` - `prof_md: Option<PathBuf>` added
- [ ] `src/cli.rs` - `--prof-md` flag registered

### Build Verification
- [ ] `cargo build --release` succeeds
- [ ] `cargo test` passes
- [ ] `cargo clippy -- -D warnings` clean

---

## 🧪 Test Execution Checklist

### L0: Smoke Tests (MUST PASS)
- [ ] `L0_001_prof_md_flag_exists` - Flag in help
- [ ] `L0_002_prof_md_creates_file` - File created
- [ ] `L0_003_prof_md_stderr_default` - stderr output

### L1: Feature Tests (MUST PASS)
- [ ] `L1_001_version_header` - Version comment
- [ ] `L1_002_summary_placement` - Summary after title
- [ ] `L1_003_hot_functions_table` - Table exists
- [ ] `L1_004_hot_functions_limit` - Max 20 entries
- [ ] `L1_005_truncation_footer` - Footer present
- [ ] `L1_006_gfm_compliance` - mdl lint passes
- [ ] `L1_007_system_env_section` - Section exists

### L2: Edge Cases (SHOULD PASS)
- [ ] `L2_001_atomic_write_crash` - No partial file
- [ ] `L2_002_empty_hot_functions` - Empty handling
- [ ] `L2_003_unicode_function_names` - UTF-8 correct
- [ ] `L2_004_snippet_truncation` - 5 lines max
- [ ] `L2_005_no_ansi_escape` - Clean output
- [ ] `L2_006_very_long_path` - Path rendering
- [ ] `L2_007_concurrent_writes` - Atomic last write

### L4: Security Tests (MUST PASS)
- [ ] `SEC_038_001_key_redaction` - API_KEY → ***
- [ ] `SEC_038_002_secret_redaction` - DB_SECRET → ***
- [ ] `SEC_038_003_token_redaction` - AUTH_TOKEN → ***
- [ ] `SEC_038_004_password_redaction` - PASSWORD → ***
- [ ] `SEC_038_005_case_insensitive` - All cases redacted
- [ ] `SEC_038_006_partial_match` - Substring match
- [ ] `SEC_038_007_non_sensitive_pass` - HOME/PATH not redacted
- [ ] `SEC_038_008_nested_secret` - SECRET_KEY_BASE redacted

### L5: Performance Tests (MUST PASS)
- [ ] `PERF_038_001_overhead_light` - <5% (small script)
- [ ] `PERF_038_002_overhead_medium` - <5% (medium script)
- [ ] `PERF_038_003_overhead_heavy` - <5% (large script)
- [ ] `PERF_038_004_file_write_speed` - <10ms

---

## 🏁 Quality Gate Checklist (RFC §10)

| Gate | Verification | Status |
|:---|:---|:---:|
| **Gate A** | `mdl report.md` exits 0 | ⬜ |
| **Gate B** | AI correctly identifies #1 bottleneck | ⬜ |
| **Gate C** | Profiled runtime ≤ 1.05x unprofiled | ⬜ |

---

## 📊 Multi-Agent Review Checklist

### Agent A (Edge Cases)
- [ ] L2 tests executed
- [ ] Edge cases documented
- [ ] Findings submitted to `reviews/AGENT-A-FINDINGS.md`

### Agent B (Stability)
- [ ] L0/L1 tests executed
- [ ] Core functionality verified
- [ ] Findings submitted to `reviews/AGENT-B-FINDINGS.md`

### Agent C (Security)
- [ ] L4 tests executed
- [ ] Secrets sanitization verified
- [ ] Findings submitted to `reviews/AGENT-C-FINDINGS.md`

### QA Leader
- [ ] Cross-review completed
- [ ] Gap analysis performed
- [ ] Quality gates verified
- [ ] Final verdict prepared

---

## 📦 Deliverables Checklist

### Documentation
- [ ] Architecture alignment verified
- [ ] Test matrix complete
- [ ] Requirements traceability updated
- [ ] Agent review documents collected
- [ ] Leader gap analysis documented

### Test Artifacts
- [ ] `test_rfc0038_prof_md.py` created
- [ ] `test_rfc0038_security.py` created
- [ ] `test_rfc0038_performance.py` created
- [ ] All tests pass or justified XFAIL

### Sign-off
- [ ] All P0 requirements verified
- [ ] All security invariants tested
- [ ] Performance threshold met
- [ ] QA Leader sign-off

---

## 🚨 Defect Tracking

| DEF ID | Description | Priority | Status |
|:---|:---|:---:|:---:|
| - | - | - | - |

---

## 📝 Notes

### Developer Pre-Delivery Requirements
Before submitting for QA, developer MUST:
1. Run `cargo test` - All pass
2. Run `cargo clippy -- -D warnings` - No warnings
3. Run `cargo fmt --check` - Formatted
4. Self-test `--prof-md` flag manually

### QA Acceptance Criteria
For **APPROVED** verdict:
- All L0/L1/L4 tests PASS
- No P0/P1 defects open
- Quality Gates A, B, C PASS
- Performance overhead < 5%

---

## 📅 Timeline

| Milestone | Target Date | Status |
|:---|:---|:---:|
| QA Phase 0 Complete | 2026-01-23 | ✅ Done |
| Implementation Complete | TBD | ⬜ Pending |
| QA Phase 1-2 (Testing) | TBD | ⬜ Pending |
| QA Verdict | TBD | ⬜ Pending |

---

**QA Working Group** | Checklist v1.0 | 2026-01-23
