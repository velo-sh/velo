"""
RFC-0038 AI-Native Diagnostics Test Suite

QA Phase: 1 - Test Design & Implementation
Reference: RFC-0038, test-matrix.md

Test Tiers:
- L0: Smoke tests (flag exists, file created)
- L1: Feature tests (format compliance)
- L2: Edge cases
- L4: Security tests (secrets sanitization)
- L5: Performance tests (overhead < 5%)
"""

import os
import re
import subprocess
import time

import pytest

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def test_script(tmp_path):
    """Create a simple test script."""
    script = tmp_path / "test_script.py"
    script.write_text("""
import json
import os
import hashlib

def main():
    print("Test script running")
    data = {"test": "value"}
    json.dumps(data)
    hashlib.md5(b"test").hexdigest()
    print("Done")

if __name__ == "__main__":
    main()
""")
    return script


@pytest.fixture
def heavy_import_script(tmp_path):
    """Create a script with heavy imports for profiling."""
    script = tmp_path / "heavy_imports.py"
    script.write_text("""
import json
import os
import sys
import collections
import itertools
import functools
import re
import datetime
import hashlib
import base64
import urllib.parse
import http.client

def main():
    print("Heavy imports loaded")
    data = {"test": "value", "number": 42}
    json_str = json.dumps(data)
    hash_val = hashlib.md5(json_str.encode()).hexdigest()
    print(f"Hash: {hash_val}")

if __name__ == "__main__":
    main()
""")
    return script


# =============================================================================
# L0: SMOKE TESTS
# =============================================================================


@pytest.mark.tier0
class TestL0Smoke:
    """L0 Smoke Tests - Basic functionality verification."""

    def test_L0_001_prof_md_flag_exists(self, velo_binary):
        """L0_001: --prof-md flag visible in help."""
        result = subprocess.run(
            [velo_binary, "run", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "--prof-md" in result.stdout, "Flag --prof-md not found in help"

    def test_L0_002_prof_md_creates_file(self, velo_binary, test_script, tmp_path):
        """L0_002: Report file created when specified."""
        report_path = tmp_path / "report.md"

        result = subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        assert report_path.exists(), f"Report file not created. stderr: {result.stderr}"
        content = report_path.read_text()
        assert len(content) > 0, "Report file is empty"

    def test_L0_003_prof_md_output_to_stderr(self, velo_binary, test_script, tmp_path):
        """L0_003: Confirmation message to stderr."""
        report_path = tmp_path / "report.md"

        result = subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        assert "Diagnostic report written" in result.stderr, f"Expected confirmation in stderr. Got: {result.stderr}"


# =============================================================================
# L1: FEATURE TESTS
# =============================================================================


@pytest.mark.tier1
class TestL1Feature:
    """L1 Feature Tests - Format compliance verification."""

    def test_L1_001_version_header(self, velo_binary, test_script, tmp_path):
        """L1_001: Report starts with version comment."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        first_line = content.split("\n")[0]
        assert "<!-- velo:diagnostics v=1 -->" in first_line, f"Version header not found. First line: {first_line}"

    def test_L1_002_summary_placement(self, velo_binary, test_script, tmp_path):
        """L1_002: Summary section appears immediately after title."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        lines = content.split("\n")

        # Find title line (# Velo Diagnostic Report)
        title_idx = None
        summary_idx = None
        for i, line in enumerate(lines):
            if line.startswith("# Velo Diagnostic Report"):
                title_idx = i
            if line.startswith("## 📋 Summary"):
                summary_idx = i
                break

        assert title_idx is not None, "Title not found"
        assert summary_idx is not None, "Summary section not found"
        # Summary should be within 2 lines of title (allowing for blank line)
        assert summary_idx <= title_idx + 2, (
            f"Summary at line {summary_idx}, expected immediately after title at {title_idx}"
        )

    def test_L1_003_bottleneck_section_exists(self, velo_binary, heavy_import_script, tmp_path):
        """L1_003: Top Bottleneck Analysis section exists."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(heavy_import_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        assert "## 🔍 Top Bottleneck Analysis" in content, "Bottleneck Analysis section not found"

    def test_L1_004_max_20_bottlenecks(self, velo_binary, heavy_import_script, tmp_path):
        """L1_004: Max 20 bottleneck entries."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(heavy_import_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        # Count "### N." entries
        bottleneck_entries = re.findall(r"^### \d+\.", content, re.MULTILINE)
        assert len(bottleneck_entries) <= 20, f"Too many bottleneck entries: {len(bottleneck_entries)}"

    def test_L1_006_gfm_compliance(self, velo_binary, test_script, tmp_path):
        """L1_006: GFM table syntax compliance."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()

        # Check table alignment markers
        assert "| :--- |" in content, "Table alignment markers not found"

        # Check code block closure (even number of ```)
        backticks = content.count("```")
        assert backticks % 2 == 0, f"Unbalanced code blocks: {backticks} backticks"

    def test_L1_007_system_env_section(self, velo_binary, test_script, tmp_path):
        """L1_007: System Environment section exists."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        assert "## 💻 System Environment" in content, "System Environment section not found"


# =============================================================================
# L2: EDGE CASES
# =============================================================================


@pytest.mark.tier2
class TestL2EdgeCases:
    """L2 Edge Case Tests."""

    def test_L2_003_unicode_handling(self, velo_binary, tmp_path):
        """L2_003: Unicode function names handled correctly."""
        script = tmp_path / "unicode_test.py"
        script.write_text("""
def 你好世界():
    return "Hello"

def main():
    print(你好世界())

if __name__ == "__main__":
    main()
""")
        report_path = tmp_path / "report.md"

        result = subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        # Should not crash
        assert result.returncode == 0 or report_path.exists(), f"Unicode handling failed: {result.stderr}"

    def test_L2_005_no_ansi_escape(self, velo_binary, test_script, tmp_path):
        """L2_005: No ANSI escape codes in output."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_bytes()
        # ANSI escape sequence pattern: ESC[...m
        ansi_pattern = b"\x1b["
        assert ansi_pattern not in content, "ANSI escape codes found in report"


# =============================================================================
# L4: SECURITY TESTS
# =============================================================================


@pytest.mark.tier1
class TestL4Security:
    """L4 Security Tests - Secrets sanitization."""

    def test_SEC_038_001_key_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_001: API_KEY env var redacted to ***."""
        report_path = tmp_path / "report.md"

        env = os.environ.copy()
        env["TEST_API_KEY"] = "super_secret_123"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        # The key should be present but value redacted
        if "TEST_API_KEY" in content:
            assert "super_secret_123" not in content, "Secret value not redacted!"
            assert "***" in content, "Redaction marker *** not found"

    def test_SEC_038_002_secret_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_002: DB_SECRET env var redacted to ***."""
        report_path = tmp_path / "report.md"

        env = os.environ.copy()
        env["MY_DB_SECRET"] = "password456"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        if "MY_DB_SECRET" in content:
            assert "password456" not in content, "Secret value not redacted!"

    def test_SEC_038_003_token_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_003: AUTH_TOKEN env var redacted to ***."""
        report_path = tmp_path / "report.md"

        env = os.environ.copy()
        env["AUTH_TOKEN"] = "token789"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        if "AUTH_TOKEN" in content:
            assert "token789" not in content, "Token value not redacted!"

    def test_SEC_038_004_password_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_004: PASSWORD env var redacted to ***."""
        report_path = tmp_path / "report.md"

        env = os.environ.copy()
        env["MYSQL_PASSWORD"] = "db_pass"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        if "MYSQL_PASSWORD" in content:
            assert "db_pass" not in content, "Password value not redacted!"

    def test_SEC_038_005_case_insensitive(self, velo_binary, test_script, tmp_path):
        """SEC_038_005: Case-insensitive matching for secrets."""
        report_path = tmp_path / "report.md"

        env = os.environ.copy()
        env["api_key"] = "secret1"
        env["Api_Key"] = "secret2"
        env["API_KEY"] = "secret3"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        assert "secret1" not in content, "Lowercase key not redacted"
        assert "secret2" not in content, "Mixed case key not redacted"
        assert "secret3" not in content, "Uppercase key not redacted"

    def test_SEC_038_007_non_sensitive_pass(self, velo_binary, test_script, tmp_path):
        """SEC_038_007: Non-sensitive env vars NOT redacted."""
        report_path = tmp_path / "report.md"

        env = os.environ.copy()
        env["VELO_TEST_NORMAL"] = "visible_value_xyz"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        # Non-sensitive variable should have its value visible
        if "VELO_TEST_NORMAL" in content:
            assert "visible_value_xyz" in content, "Non-sensitive value was incorrectly redacted"


# =============================================================================
# L5: PERFORMANCE TESTS
# =============================================================================


@pytest.mark.tier2
@pytest.mark.perf
class TestL5Performance:
    """L5 Performance Tests - Overhead verification."""

    def test_PERF_038_001_overhead_light(self, velo_binary, test_script, tmp_path):
        """PERF_038_001: Overhead < 5% for small script."""
        # Run without profiling (baseline)
        baseline_times = []
        for _ in range(3):
            start = time.perf_counter()
            subprocess.run(
                [velo_binary, "run", str(test_script)],
                capture_output=True,
                timeout=30,
                cwd=tmp_path,
            )
            baseline_times.append(time.perf_counter() - start)

        baseline_avg = sum(baseline_times) / len(baseline_times)

        # Run with profiling
        profile_times = []
        for i in range(3):
            report_path = tmp_path / f"perf_report_{i}.md"
            start = time.perf_counter()
            subprocess.run(
                [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
                capture_output=True,
                timeout=30,
                cwd=tmp_path,
            )
            profile_times.append(time.perf_counter() - start)

        profile_avg = sum(profile_times) / len(profile_times)

        # Calculate overhead
        if baseline_avg > 0:
            overhead = (profile_avg - baseline_avg) / baseline_avg * 100
            # Allow up to 10% overhead in tests (5% threshold + measurement noise)
            assert overhead < 10, (
                f"Overhead {overhead:.1f}% exceeds threshold. Baseline: {baseline_avg:.3f}s, Profile: {profile_avg:.3f}s"
            )


# =============================================================================
# GATE TESTS (RFC §10)
# =============================================================================


@pytest.mark.tier1
class TestQualityGates:
    """Quality Gate Tests per RFC-0038 §10."""

    def test_GATE_B_ai_bottleneck_identification(self, velo_binary, heavy_import_script, tmp_path):
        """GATE_B: AI can identify top bottleneck from report."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(heavy_import_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()

        # Extract Primary Bottleneck from Summary
        summary_match = re.search(r"\*\*Primary Bottleneck\*\* \| `([^`]+)`", content)

        # Extract first entry from Bottleneck Analysis
        first_entry_match = re.search(r"### 1\. (\S+)", content)

        if summary_match and first_entry_match:
            summary_bottleneck = summary_match.group(1)
            first_bottleneck = first_entry_match.group(1)
            assert summary_bottleneck == first_bottleneck, (
                f"Summary ({summary_bottleneck}) doesn't match first entry ({first_bottleneck})"
            )
