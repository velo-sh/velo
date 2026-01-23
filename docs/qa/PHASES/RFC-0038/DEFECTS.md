# RFC-0038 Defect Report

**QA Engineer**: AI Agent (QA Role)  
**Date**: 2026-01-23  
**Status**: ACTIVE  
**Total Defects Found**: 11

---

## Critical Defects (P0)

### BUG-001: GFM Table Column Count Mismatch (P0)

**Severity**: P0 - RFC Protocol Violation  
**Category**: Output Format  
**Status**: OPEN

**Description**:  
The Summary table in `--prof-md` output has inconsistent column counts. The header defines 2 columns (`Key | Value`), but the "Memory Delta" row has 3 columns, violating GFM table standards.

**Evidence**:
```markdown
| Key | Value |
| :--- | :--- |
| **Total Runtime** | 22.89ms |
| **Primary Bottleneck** | N/A |
| **Memory Delta** | +0.1MB | ✅ COW Efficient |  ← 3 COLUMNS!
| **Optimization Budget**| CPU-bound |
| **Status** | 🟢 Within Budget |
```

**Expected Behavior**:  
All rows must have exactly 2 columns, matching the header definition.

**RFC Reference**: §3.2 "Output must follow GitHub Flavored Markdown (GFM) standards"

**Location**: `src/common/diagnostics.rs:54-62`

**Fix Suggestion**:
```rust
// Change from:
md.push_str(&format!(
    "| **Memory Delta** | {:+.1}MB | {} |\n",
    memory_delta_mb,
    if memory_delta_mb < 50.0 { "✅ COW Efficient" } else { "⚠️ Heavy Allocation" }
));

// To:
md.push_str(&format!(
    "| **Memory Delta** | {:+.1}MB {} |\n",
    memory_delta_mb,
    if memory_delta_mb < 50.0 { "✅ COW Efficient" } else { "⚠️ Heavy Allocation" }
));
```

---

### BUG-002: JSON Output Does NOT Use Atomic Write (P0)

**Severity**: P0 - Data Integrity Violation  
**Category**: File I/O  
**Status**: OPEN

**Description**:  
Markdown output uses `write_atomic()` for safe file writing, but JSON output uses `std::fs::write()` directly. This violates RFC-0038's requirement for atomic file operations.

**Evidence**:
```rust
// Line 372 - Markdown uses atomic write:
MarkdownFormatter::write_atomic(prof_md_path, &report)?;

// Line 416 - JSON uses direct write:
std::fs::write(prof_json_path, &report)?;
```

**Impact**:  
- File corruption on crash during write
- Incomplete JSON files causing parse errors
- Inconsistent behavior between `--prof-md` and `--prof-json`

**Location**: `src/cmd/run.rs:416`

**Fix Suggestion**:
```rust
MarkdownFormatter::write_atomic(prof_json_path, &report)?;
```

---

### BUG-003: JSON Output Skips ANSI Stripping (P0)

**Severity**: P0 - RFC Protocol Violation  
**Category**: Output Purity  
**Status**: OPEN

**Description**:  
Markdown output calls `strip_ansi()` via `write_atomic()`, but JSON output bypasses this entirely. If any bottleneck names or values contain ANSI escape codes, they will leak into the JSON.

**Evidence**:
```rust
// write_atomic includes strip_ansi:
pub fn write_atomic(path: &Path, content: &str) -> Result<()> {
    let stripped = Self::strip_ansi(content);  // ← Markdown gets cleaned
    ...
}

// JSON uses direct write - no stripping:
let report = formatter.format_json(...);
std::fs::write(prof_json_path, &report)?;  // ← JSON may contain ANSI
```

**RFC Reference**: §3.2 "ANSI Noise: Escape codes confuse smaller LLMs"

**Location**: `src/cmd/run.rs:409-416`

---

## High Defects (P1)

### BUG-004: Hardcoded `app_entry_ms = total_time / 10` (P1)

**Severity**: P1 - Inaccurate Data  
**Category**: Calculation Logic  
**Status**: OPEN

**Description**:  
The `app_entry_ms` value in the timeline is calculated as `total_time.as_millis() / 10`, which is an arbitrary magic number with no basis in reality.

**Evidence**:
```rust
// Appears 3 times in run.rs:
app_entry_ms: total_time.as_millis() as u64 / 10,
```

**Impact**:  
- Timeline data is fabricated, not measured
- AI agents will receive incorrect performance data
- Undermines the value of the diagnostic report

**Location**: `src/cmd/run.rs:351, 395, 533`

**Fix Suggestion**:  
Use actual timing measurements from the profile data, or clearly label this as "estimated" in the output.

---

### BUG-005: Hardcoded Status Values (P1)

**Severity**: P1 - Misleading Data  
**Category**: Business Logic  
**Status**: OPEN

**Description**:  
The following values are always hardcoded regardless of actual performance:
- `Optimization Budget` = `"CPU-bound"` (always)
- `Status` = `"🟢 Within Budget"` (always)

**Evidence**:
```rust
// src/common/diagnostics.rs:63-64
md.push_str("| **Optimization Budget**| CPU-bound |\n");
md.push_str("| **Status** | 🟢 Within Budget |\n\n");
```

**Impact**:  
- The diagnostic report always shows "Within Budget" even when performance is poor
- AI agents cannot trust the status field
- Violates the principle of accurate diagnostics

---

### BUG-006: Regex Compiled on Every Call (P1)

**Severity**: P1 - Performance Issue  
**Category**: Performance  
**Status**: OPEN

**Description**:  
The `strip_ansi` function compiles the regex pattern on every invocation instead of using a lazy static.

**Evidence**:
```rust
fn strip_ansi(text: &str) -> String {
    let re = Regex::new(r"\x1B\[[0-9;]*[a-zA-Z]").unwrap();  // Compiled every call!
    re.replace_all(text, "").to_string()
}
```

**Impact**:  
- Unnecessary CPU overhead
- Violates Velo's "high-performance" positioning

**Location**: `src/common/diagnostics.rs:233-236`

**Fix Suggestion**:
```rust
use once_cell::sync::Lazy;

static ANSI_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\x1B\[[0-9;]*[a-zA-Z]").unwrap()
});

fn strip_ansi(text: &str) -> String {
    ANSI_RE.replace_all(text, "").to_string()
}
```

---

### BUG-007: Race Condition in Atomic Write (P1)

**Severity**: P1 - Concurrency Issue  
**Category**: Concurrency  
**Status**: OPEN

**Description**:  
The atomic write uses a fixed `.tmp` extension. If two processes run simultaneously with the same output path, they will overwrite each other's temporary files.

**Evidence**:
```rust
let temp_path = path.with_extension("tmp");  // Always "report.tmp"
```

**Impact**:  
- Data corruption in CI environments running parallel tests
- Race condition in multi-process scenarios

**Location**: `src/common/diagnostics.rs:166`

**Fix Suggestion**:
```rust
let temp_path = path.with_extension(format!("tmp.{}", std::process::id()));
// Or use tempfile crate for safer handling
```

---

## Medium Defects (P2)

### BUG-008: Privacy Leak - User Paths in Report (P2)

**Severity**: P2 - Privacy Concern  
**Category**: Security / Privacy  
**Status**: OPEN

**Description**:  
The environment section leaks potentially sensitive user information:
- `HOME` = `/Users/antigravity`
- `LOGNAME` = `antigravity`
- `PWD` = full working directory path
- `PATH` = user's full PATH variable
- `CURSOR_TRACE_ID` = tracking identifier

**Evidence**:
```markdown
| **HOME** | `/Users/antigravity` |
| **LOGNAME** | `antigravity` |
| **PWD** | `/Users/antigravity/.cursor/worktrees/...` |
```

**Impact**:  
- Username disclosure
- Directory structure disclosure
- Potential correlation with external tracking IDs

**Fix Suggestion**:  
Add path sanitization to replace `/Users/<username>` with `~` or `$HOME`.

---

### BUG-009: Mermaid Timeline Math is Suspicious (P2)

**Severity**: P2 - Logic Error  
**Category**: Calculation Logic  
**Status**: OPEN

**Description**:  
The Mermaid timeline uses hardcoded offsets that don't make logical sense:

**Evidence**:
```rust
md.push_str(&format!(
    "    Env Shield   : {}, {}\n",
    timeline.zygote_ms.saturating_sub(2),  // Start BEFORE zygote?
    timeline.zygote_ms + 4                  // Magic number +4
));
```

**Impact**:  
- Timeline visualization is inaccurate
- "Env Shield" starts at `zygote_ms - 2` which implies it starts before Zygote

---

### BUG-010: RFC Deviations in Output Schema (P2)

**Severity**: P2 - Specification Mismatch  
**Category**: RFC Compliance  
**Status**: OPEN

**Description**:  
Several RFC-defined elements are missing or different from the spec:

| RFC Requirement | Actual Implementation |
|-----------------|----------------------|
| Table: `Startup (Zygote)` with `⚡ Instant` status | Missing from output |
| "Hot Functions" table section | Missing from output |
| Signature field in bottleneck | Missing |
| `velo_version` in JSON | Missing |

---

### BUG-011: Typo in Output - Missing Space (P2)

**Severity**: P2 - Cosmetic  
**Category**: Output Format  
**Status**: OPEN

**Description**:  
There's a missing space before the pipe character in one line:

**Evidence**:
```rust
md.push_str("| **Optimization Budget**| CPU-bound |\n");
//                                  ^ Missing space before |
```

---

## Summary Statistics

| Priority | Count | Status |
|----------|-------|--------|
| P0 (Critical) | 3 | OPEN |
| P1 (High) | 4 | OPEN |
| P2 (Medium) | 4 | OPEN |
| **Total** | **11** | **ALL OPEN** |

---

## Recommendation

**QA Verdict**: ❌ **FAIL** - Cannot sign off on RFC-0038 implementation.

The implementation has 3 critical (P0) defects that violate the RFC protocol and data integrity requirements. These must be fixed before the feature can be considered complete.

**Required Actions**:
1. Fix BUG-001 (GFM Table format) - 5 min
2. Fix BUG-002 (JSON atomic write) - 2 min  
3. Fix BUG-003 (JSON ANSI stripping) - 5 min
4. Fix BUG-004 (Hardcoded timeline) - 30 min (investigation needed)
5. Fix BUG-005 (Hardcoded status) - 30 min (logic needed)

**After P0 fixes, re-run QA verification.**

---

*Generated by QA Agent following QA-SOP v1.0*
