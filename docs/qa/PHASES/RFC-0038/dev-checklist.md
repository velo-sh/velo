# RFC-0038 Developer Pre-Delivery Checklist

> **For**: Developer implementing RFC-0038
> **Target Version**: v0.9.5
> **Date**: 2026-01-23
> **Effort Estimate**: 2-3 Days

---

## ✅ Before Submitting for QA Review

### Build & Lint
```bash
# All must pass:
cargo build --release
cargo test
cargo clippy --all-targets --all-features -- -D warnings
cargo fmt --check
```

- [ ] `cargo build --release` - SUCCESS
- [ ] `cargo test` - All tests pass
- [ ] `cargo clippy -- -D warnings` - No warnings
- [ ] `cargo fmt --check` - Properly formatted

---

### Self-Test: Core Functionality

```bash
# 1. Flag exists
velo run --help | grep -q "prof-md" && echo "✓ Flag exists"

# 2. Creates file
velo run --prof-md=test_report.md examples/simple.py
[ -f test_report.md ] && echo "✓ File created"

# 3. Check version header
head -1 test_report.md | grep -q "velo:diagnostics" && echo "✓ Version header"

# 4. Check Summary section
grep -q "## 📋 Summary" test_report.md && echo "✓ Summary section"

# 5. Check Hot Functions table
grep -q "## Hot Functions" test_report.md && echo "✓ Hot Functions table"
```

- [ ] `--prof-md` flag visible in help
- [ ] Report file created when specified
- [ ] Version header `<!-- velo:diagnostics v=1 -->` present
- [ ] `## 📋 Summary` section present
- [ ] `## Hot Functions` table present

---

### Self-Test: Secrets Sanitization

```bash
# Set test env vars
export TEST_API_KEY="super_secret_123"
export TEST_DB_SECRET="password456"
export TEST_AUTH_TOKEN="token789"
export NORMAL_VAR="visible_value"

# Run profiler
velo run --prof-md=secrets_test.md examples/simple.py

# Check redaction
grep "TEST_API_KEY" secrets_test.md | grep -q "\*\*\*" && echo "✓ API_KEY redacted"
grep "TEST_DB_SECRET" secrets_test.md | grep -q "\*\*\*" && echo "✓ SECRET redacted"
grep "TEST_AUTH_TOKEN" secrets_test.md | grep -q "\*\*\*" && echo "✓ TOKEN redacted"
grep "NORMAL_VAR" secrets_test.md | grep -q "visible_value" && echo "✓ Non-sensitive passed"
```

- [ ] `KEY` env vars redacted to `***`
- [ ] `SECRET` env vars redacted to `***`
- [ ] `TOKEN` env vars redacted to `***`
- [ ] `PASSWORD` env vars redacted to `***`
- [ ] Non-sensitive vars NOT redacted

---

### Self-Test: Format Compliance

```bash
# If mdl is installed:
mdl test_report.md && echo "✓ Markdown lint passes"

# Check for ANSI escapes (should find none)
grep -P '\x1b\[' test_report.md || echo "✓ No ANSI escapes"

# Check truncation (if >20 functions)
grep -q "...and.*other" test_report.md && echo "✓ Truncation footer"
```

- [ ] `mdl` lint passes (or manual check)
- [ ] No ANSI escape codes in output
- [ ] Truncation footer if >20 functions

---

### Self-Test: Performance Overhead

```bash
# Run without profiling
time velo run examples/benchmark_script.py  # Note: Xms

# Run with profiling
time velo run --prof-md=perf.md examples/benchmark_script.py  # Note: Yms

# Calculate: (Y - X) / X < 5%
```

- [ ] Overhead < 5% verified

---

## 📋 Implementation Checklist

### New File: `src/common/diagnostics.rs`
- [ ] `MarkdownFormatter` struct implemented
- [ ] `format_summary()` method
- [ ] `format_hot_functions()` method with Top 20 limit
- [ ] `format_environment()` method with sanitizer
- [ ] `sensitive_key_filter()` for KEY/SECRET/TOKEN/PASSWORD
- [ ] ANSI strip using `strip-ansi-escapes`
- [ ] UTF-8 validation

### Modified: `src/cmd/run.rs`
- [ ] `prof_md: Option<PathBuf>` argument added
- [ ] Atomic file write implementation
- [ ] Write to stderr if no file specified

### Modified: `src/cli.rs`
- [ ] `--prof-md` flag registered
- [ ] Help text matches RFC description

---

## 🔗 References

| Document | Purpose |
|:---|:---|
| [RFC-0038](../../../rfcs/0038-ai-native-diagnostics.md) | Full specification |
| [Architecture Alignment](./architecture-alignment.md) | QA requirement mapping |
| [Test Matrix](./test-matrix.md) | All test cases |
| [QA Checklist](./qa-checklist.md) | QA verification steps |

---

## 📤 Submission

When ready for QA:

1. **Commit with message**: `feat(diagnostics): implement RFC-0038 AI-Native Diagnostics`
2. **Reference**: Include "Implements RFC-0038" in PR description
3. **Notify**: Tag QA Working Group for review

---

**Velo Developer Checklist** | RFC-0038 | 2026-01-23
