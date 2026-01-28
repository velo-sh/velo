# RFC-0038 Test Matrix

> **Phase**: RFC-0038 AI-Native Diagnostics
> **Version**: v0.9.5
> **Date**: 2026-01-23
> **Reference**: [RFC-0038](../../../rfcs/0038-ai-native-diagnostics.md) | [Architecture Alignment](./architecture-alignment.md)

---

## 1. Test Suite Structure

```
tests/qa/
├── test_rfc0038_prof_md.py           # L0-L2: Core functionality
├── test_rfc0038_security.py          # L4: Secrets sanitization
└── test_rfc0038_performance.py       # L5: Overhead benchmarks
```

---

## 2. L0: Smoke Tests (Core Correctness)

| Test ID | Description | Expected | Priority |
|:---|:---|:---|:---:|
| `L0_001_prof_md_flag_exists` | `velo run --help` shows `--prof-md` | Flag visible in help | **P0** |
| `L0_002_prof_md_creates_file` | `velo run --prof-md=report.md script.py` | `report.md` created | **P0** |
| `L0_003_prof_md_stderr_default` | `velo run --prof-md script.py` (no file) | Output to stderr | **P0** |

---

## 3. L1: Feature Tests (Format Compliance)

| Test ID | Description | Expected | Priority |
|:---|:---|:---|:---:|
| `L1_001_version_header` | Report starts with `<!-- velo:diagnostics v=1 -->` | Version comment present | **P0** |
| `L1_002_summary_placement` | `## 📋 Summary` appears immediately after title | Correct structure | **P0** |
| `L1_003_hot_functions_table` | Report contains `## Hot Functions` table | Table exists | **P0** |
| `L1_004_hot_functions_limit` | Table has max 20 entries | Count ≤ 20 | **P1** |
| `L1_005_truncation_footer` | Truncated table shows "...and N other calls" | Footer present | **P1** |
| `L1_006_gfm_compliance` | Output passes `mdl` lint | No lint errors | **P0** |
| `L1_007_system_env_section` | `## 💻 System Environment` section exists | Section present | **P1** |

---

## 4. L2: Edge Cases

| Test ID | Description | Expected | Priority |
|:---|:---|:---|:---:|
| `L2_001_atomic_write_crash` | Kill process during write | No partial file | **P0** |
| `L2_002_empty_hot_functions` | Script with no measurable functions | Empty table or "N/A" | **P2** |
| `L2_003_unicode_function_names` | Function names with unicode | Correct UTF-8 rendering | **P1** |
| `L2_004_snippet_truncation` | Long function signature (>5 lines) | Truncated to 5 lines | **P1** |
| `L2_005_no_ansi_escape` | Output contains no ANSI codes | Clean Markdown | **P0** |
| `L2_006_very_long_path` | Script in deeply nested path | Path rendered correctly | **P2** |
| `L2_007_concurrent_writes` | Multiple `--prof-md` to same file | Last write wins, atomic | **P1** |

---

## 5. L4: Security Tests

| Test ID | Description | Expected | Priority |
|:---|:---|:---|:---:|
| `SEC_038_001_key_redaction` | Env var `API_KEY=secret123` | Value shows `***` | **P0** |
| `SEC_038_002_secret_redaction` | Env var `DB_SECRET=password` | Value shows `***` | **P0** |
| `SEC_038_003_token_redaction` | Env var `AUTH_TOKEN=xyz` | Value shows `***` | **P0** |
| `SEC_038_004_password_redaction` | Env var `MYSQL_PASSWORD=abc` | Value shows `***` | **P0** |
| `SEC_038_005_case_insensitive` | Env var `api_key`, `Api_Key`, `API_KEY` | All redacted | **P0** |
| `SEC_038_006_partial_match` | Env var `MY_API_KEY_EXTRA` | Redacted | **P1** |
| `SEC_038_007_non_sensitive_pass` | Env var `HOME`, `PATH`, `USER` | NOT redacted | **P1** |
| `SEC_038_008_nested_secret` | Env var `SECRET_KEY_BASE` | Redacted | **P1** |

---

## 6. L5: Performance Tests

| Test ID | Description | Threshold | Priority |
|:---|:---|:---:|:---:|
| `PERF_038_001_overhead_light` | Small script (10 imports) | < 5% overhead | **P0** |
| `PERF_038_002_overhead_medium` | Medium script (50 imports) | < 5% overhead | **P0** |
| `PERF_038_003_overhead_heavy` | Heavy script (100+ imports) | < 5% overhead | **P1** |
| `PERF_038_004_file_write_speed` | Large report (1000 functions) | < 10ms write | **P2** |

---

## 7. Gate Tests (RFC §10)

| Gate | Test ID | Description | Pass Criteria |
|:---|:---|:---|:---|
| **A** | `GATE_A_mdl_lint` | Run `mdl` on generated report | Exit code 0 |
| **B** | `GATE_B_ai_bottleneck` | Claude/Gemini identifies top bottleneck | Matches actual #1 |
| **C** | `GATE_C_overhead` | Compare profiled vs unprofiled runtime | Diff < 5% |

---

## 8. Test Environment Requirements

| Requirement | Details |
|:---|:---|
| **Binary** | `velo` built with `--release` |
| **Python** | 3.11+ |
| **Tools** | `mdl` (Markdown linter) installed |
| **Isolation** | Each test uses `tempfile.TemporaryDirectory()` |
| **Cleanup** | Processes killed, temp files removed |

---

## 9. Agent Assignment

| Agent | Tests | Focus |
|:---|:---|:---|
| **Agent A (Edge)** | L2-001 to L2-007 | Edge cases, boundary conditions |
| **Agent B (Stability)** | L0, L1 | Core functionality verification |
| **Agent C (Security)** | SEC-038-001 to SEC-038-008 | Secrets sanitization |
| **QA Leader** | GATE_A, GATE_B, GATE_C | Quality gates verification |

---

## 10. Coverage Summary

| Tier | Test Count | Coverage Target |
|:---:|:---:|:---:|
| L0 (Smoke) | 3 | 100% |
| L1 (Feature) | 7 | 100% |
| L2 (Edge) | 7 | 85% |
| L4 (Security) | 8 | 100% |
| L5 (Performance) | 4 | 100% |
| **Total** | **29** | **95%** |

---

## 11. Risk Assessment

| Risk | Impact | Mitigation |
|:---|:---:|:---|
| Atomic write implementation complex | Medium | Test with signal interrupts |
| ANSI escape codes leak through | Low | Use `strip-ansi-escapes` crate |
| Performance overhead exceeds 5% | High | Profile `MarkdownFormatter` |
| Secrets filter too aggressive | Medium | Test non-sensitive env vars pass through |

---

**QA Working Group** | Test Matrix v1.0 | 2026-01-23
