# RFC-0038 Architecture Alignment

> **QA Phase**: 0 (Pre-Work)
> **Date**: 2026-01-23
> **RFC**: [RFC-0038: AI-Native Diagnostics](../../../rfcs/0038-ai-native-diagnostics.md)
> **Authority**: [Developer Handoff Ticket](file:///Users/antigravity/.gemini/antigravity/brain/fec569f9-8ffa-4ea6-b909-1312998ea1c2/handoff_developer_rfc_0038.md.resolved)

---

## 1. RFC Summary

RFC-0038 defines an **AI-Native Diagnostics** protocol for Velo, enabling structured Markdown output (`--prof-md`) for performance-critical commands. This allows AI agents to parse, analyze, and optimize Python applications without regex-based guesswork.

---

## 2. Testable Requirements (MUST/SHALL/SHOULD)

### 2.1 P0 Requirements (From Handoff Ticket)

| ID | Requirement | RFC Section | Test Priority |
|:---|:---|:---:|:---:|
| **REQ-001** | Add `--prof-md` flag to `velo run` | §3.1, §4.1 | **L0** |
| **REQ-002** | Secrets Sanitizer (`KEY`, `SECRET`, `TOKEN`, `PASSWORD`) | §3.2 (CAUTION) | **L4** (Security) |
| **REQ-003** | Top 20 Hot Functions table with truncation footer | §3.1 | **L1** |
| **REQ-004** | Atomic file write (no partial MD on crash) | §4.3 | **L2** |
| **REQ-005** | Gate C: Overhead < 5% | §10 | **L5** (Performance) |

### 2.2 Protocol Requirements (From RFC)

| ID | Requirement | RFC Section | Test Priority |
|:---|:---|:---:|:---:|
| **REQ-006** | Output to `stderr` or specified file | §3.1 | **L0** |
| **REQ-007** | GFM (GitHub Flavored Markdown) compliance | §3.2 | **L1** |
| **REQ-008** | `## 📋 Summary` MUST appear immediately after title | §3.2 (IMPORTANT) | **L1** |
| **REQ-009** | Snippet bounds: Top 5 lines max | §3.2 (CAUTION) | **L2** |
| **REQ-010** | Version comment: `<!-- velo:diagnostics v=1 -->` | §3.2 | **L1** |
| **REQ-011** | Agent Hints derived from telemetry, not speculation | §4.4 | **L2** |

---

## 3. Security Invariants

| ID | Invariant | RFC Section | Test Type |
|:---|:---|:---:|:---|
| **SEC-038-001** | Env vars with `KEY/SECRET/TOKEN/PASSWORD` redacted to `***` | §3.2 | Positive + Negative |
| **SEC-038-002** | No ANSI escape codes in output | §4.2 | Validation |
| **SEC-038-003** | UTF-8 compatibility verified | §4.2 | Edge case |

---

## 4. Performance Requirements

| ID | Requirement | Threshold | RFC Section |
|:---|:---|:---:|:---:|
| **PERF-038-001** | Profiling overhead | < 5% of total execution | §10 (Gate C) |

---

## 5. Quality Gates (From RFC §10)

| Gate | Description | Verification Method |
|:---|:---|:---|
| **Gate A** | Output passes `mdl` linting | Automated lint check |
| **Gate B** | AI identifies top bottleneck from report | Manual AI test (Claude/Gemini) |
| **Gate C** | Overhead < 5% | Benchmark profiled vs unprofiled |

---

## 6. Out of Scope (v0.9.5)

Per Handoff Ticket, the following are **NOT** tested in this phase:

- `--prof-json` (deferred to v1.1)
- `velo diff` differential analysis (Future RFC)
- OpenTelemetry Span IDs (Future)

---

## 7. Architecture Alignment Checklist

- [x] RFC document read and understood
- [x] All MUST requirements extracted (count: **11**)
- [x] All security invariants identified (SEC-038-001 to SEC-038-003)
- [x] Performance thresholds documented (< 5% overhead)
- [x] Edge cases identified from design
- [x] Known limitations documented (Out of Scope)
- [ ] Test matrix created

---

## 8. Test Tier Assignment

| Tier | Tests | Run Frequency |
|:---:|:---|:---|
| **L0** | REQ-001 (flag exists), REQ-006 (output dest) | Every commit |
| **L1** | REQ-003, REQ-007, REQ-008, REQ-010 (format compliance) | Every PR |
| **L2** | REQ-004 (atomicity), REQ-009, REQ-011 (edge cases) | Daily |
| **L4** | REQ-002, SEC-038-001 (security) | Every release |
| **L5** | REQ-005, PERF-038-001 (performance) | Nightly |

---

## 9. Implementation Files to Monitor

| File | Change | Status |
|:---|:---|:---:|
| `src/common/diagnostics.rs` | NEW: `MarkdownFormatter` struct | 🔴 Not Started |
| `src/cmd/run.rs` | Add `prof_md: Option<PathBuf>` arg | 🔴 Not Started |
| `src/cli.rs` | Register `--prof-md` flag | 🔴 Not Started |

---

**QA Leader Signature**: QA Working Group
**Date**: 2026-01-23
