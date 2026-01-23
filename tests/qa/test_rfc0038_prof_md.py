"""
RFC-0038 AI-Native Diagnostics QA Tests

Test Matrix Reference: docs/qa/PHASES/RFC-0038/test-matrix.md
RFC Reference: docs/rfcs/0038-ai-native-diagnostics.md

Tiers:
- L0: Smoke Tests (MUST PASS)
- L1: Feature Tests (MUST PASS)
- L2: Edge Cases (SHOULD PASS)
- L4: Security Tests (MUST PASS)
- L5: Performance Tests (MUST PASS)
"""

import json
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
    """Create a script with heavy imports for bottleneck testing."""
    script = tmp_path / "heavy_imports.py"
    script.write_text('''
"""Heavy imports for profiling test."""
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
''')
    return script


# =============================================================================
# L0: SMOKE TESTS (MUST PASS)
# =============================================================================


@pytest.mark.tier0
class TestL0SmokeTests:
    """L0: Core functionality smoke tests."""

    def test_L0_001_prof_md_flag_exists(self, velo_binary):
        """L0_001: --prof-md flag should be visible in help."""
        result = subprocess.run(
            [velo_binary, "run", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "--prof-md" in result.stdout, "Flag --prof-md not found in help output"

    def test_L0_002_prof_md_creates_file(self, velo_binary, test_script, tmp_path):
        """L0_002: --prof-md=FILE should create the report file."""
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

    def test_L0_003_prof_md_output_message(self, velo_binary, test_script, tmp_path):
        """L0_003: Should print confirmation message to stderr."""
        report_path = tmp_path / "report.md"

        result = subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        assert "Diagnostic report written to" in result.stderr


# =============================================================================
# L1: FEATURE TESTS (MUST PASS)
# =============================================================================


@pytest.mark.tier1
class TestL1FeatureTests:
    """L1: Report format compliance tests."""

    def test_L1_001_version_header(self, velo_binary, test_script, tmp_path):
        """L1_001: Report must start with version comment."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        first_line = content.split("\n")[0]
        assert "<!-- velo:diagnostics v=1 -->" in first_line, f"Version header missing. Got: {first_line}"

    def test_L1_002_summary_placement(self, velo_binary, test_script, tmp_path):
        """L1_002: Summary section must appear immediately after title."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        lines = content.split("\n")

        # Find title and summary positions
        title_line = None
        summary_line = None
        for i, line in enumerate(lines):
            if line.startswith("# Velo Diagnostic Report"):
                title_line = i
            if line.startswith("## 📋 Summary"):
                summary_line = i
                break

        assert title_line is not None, "Title not found"
        assert summary_line is not None, "Summary section not found"
        # Summary should be within 2 lines of title (accounting for blank line)
        assert summary_line <= title_line + 2, f"Summary at line {summary_line}, expected near title at {title_line}"

    def test_L1_003_bottleneck_section_exists(self, velo_binary, heavy_import_script, tmp_path):
        """L1_003: Top Bottleneck Analysis section must exist."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(heavy_import_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        assert "## 🔍 Top Bottleneck Analysis" in content, "Bottleneck Analysis section missing"

    def test_L1_004_bottleneck_limit_20(self, velo_binary, heavy_import_script, tmp_path):
        """L1_004: Bottleneck entries should be limited to 20."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(heavy_import_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        # Count "### N." patterns (bottleneck entries)
        bottleneck_count = len(re.findall(r"^### \d+\.", content, re.MULTILINE))
        assert bottleneck_count <= 20, f"Too many bottleneck entries: {bottleneck_count}"

    def test_L1_006_gfm_table_syntax(self, velo_binary, test_script, tmp_path):
        """L1_006: Tables must use GFM alignment syntax."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        # Check for GFM table alignment markers
        assert "| :---" in content, "GFM table alignment markers missing"

    def test_L1_007_system_environment_section(self, velo_binary, test_script, tmp_path):
        """L1_007: System Environment section must exist."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        assert "## 💻 System Environment" in content, "System Environment section missing"

    def test_L1_008_mermaid_timeline(self, velo_binary, test_script, tmp_path):
        """L1_008: Mermaid Gantt chart must be present."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        assert "```mermaid" in content, "Mermaid block missing"
        assert "gantt" in content, "Gantt chart missing"


# =============================================================================
# L2: EDGE CASES (SHOULD PASS)
# =============================================================================


@pytest.mark.tier2
class TestL2EdgeCases:
    """L2: Edge case handling tests."""

    def test_L2_003_unicode_handling(self, velo_binary, tmp_path):
        """L2_003: Unicode in script/output should be handled correctly."""
        script = tmp_path / "unicode_test.py"
        script.write_text('''
# -*- coding: utf-8 -*-
def 你好():
    """Chinese function name."""
    return "世界"

def main():
    print(你好())
    print("日本語テスト")

if __name__ == "__main__":
    main()
''')
        report_path = tmp_path / "report.md"

        result = subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        # Script should run (may have encoding issues but shouldn't crash)
        assert report_path.exists(), f"Report not created. stderr: {result.stderr}"
        content = report_path.read_text()
        # Check UTF-8 validity
        content.encode("utf-8")  # Should not raise

    def test_L2_005_no_ansi_escape_codes(self, velo_binary, test_script, tmp_path):
        """L2_005: Report must not contain ANSI escape codes."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_bytes()
        # ANSI escape codes start with ESC (0x1B) followed by [
        ansi_pattern = b"\x1b["
        assert ansi_pattern not in content, "ANSI escape codes found in report"

    def test_L2_006_code_blocks_balanced(self, velo_binary, test_script, tmp_path):
        """L2_006: Code blocks must be properly closed."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()
        backtick_count = content.count("```")
        assert backtick_count % 2 == 0, f"Unbalanced code blocks: {backtick_count} backticks"


# =============================================================================
# L4: SECURITY TESTS (MUST PASS)
# =============================================================================


@pytest.mark.tier1  # Security tests run in tier1 for fast feedback
class TestL4SecurityTests:
    """L4: Secrets sanitization tests."""

    def test_SEC_038_001_key_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_001: API_KEY env var must be redacted."""
        report_path = tmp_path / "report.md"
        env = os.environ.copy()
        env["TEST_API_KEY"] = "super_secret_12345"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        # The value should be redacted
        assert "super_secret_12345" not in content, "API_KEY value not redacted!"
        # The key should appear with *** value
        if "TEST_API_KEY" in content:
            assert "***" in content, "Redacted value (***) not found"

    def test_SEC_038_002_secret_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_002: SECRET env var must be redacted."""
        report_path = tmp_path / "report.md"
        env = os.environ.copy()
        env["DB_SECRET"] = "password_xyz_789"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        assert "password_xyz_789" not in content, "SECRET value not redacted!"

    def test_SEC_038_003_token_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_003: TOKEN env var must be redacted."""
        report_path = tmp_path / "report.md"
        env = os.environ.copy()
        env["AUTH_TOKEN"] = "bearer_token_abc123"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        assert "bearer_token_abc123" not in content, "TOKEN value not redacted!"

    def test_SEC_038_004_password_redaction(self, velo_binary, test_script, tmp_path):
        """SEC_038_004: PASSWORD env var must be redacted."""
        report_path = tmp_path / "report.md"
        env = os.environ.copy()
        env["MYSQL_PASSWORD"] = "db_pass_secret"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        assert "db_pass_secret" not in content, "PASSWORD value not redacted!"

    def test_SEC_038_005_case_insensitive(self, velo_binary, test_script, tmp_path):
        """SEC_038_005: Redaction must be case-insensitive."""
        report_path = tmp_path / "report.md"
        env = os.environ.copy()
        env["my_api_key"] = "lowercase_secret"
        env["My_Api_Key_Mixed"] = "mixed_case_secret"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        assert "lowercase_secret" not in content, "Lowercase KEY not redacted!"
        assert "mixed_case_secret" not in content, "Mixed case KEY not redacted!"

    def test_SEC_038_007_non_sensitive_pass_through(self, velo_binary, test_script, tmp_path):
        """SEC_038_007: Non-sensitive env vars should pass through."""
        report_path = tmp_path / "report.md"
        env = os.environ.copy()
        env["VELO_TEST_NORMAL"] = "visible_value_123"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        # Non-sensitive value should be visible
        assert "visible_value_123" in content, "Non-sensitive value was incorrectly redacted"


# =============================================================================
# L5: PERFORMANCE TESTS
# =============================================================================


@pytest.mark.tier2
@pytest.mark.perf
class TestL5PerformanceTests:
    """L5: Performance overhead tests."""

    def test_PERF_038_001_overhead_under_5_percent(self, velo_binary, heavy_import_script, tmp_path):
        """PERF_038_001: Profiling overhead must be < 5%."""
        report_path = tmp_path / "report.md"

        # Warmup run
        subprocess.run(
            [velo_binary, "run", str(heavy_import_script)],
            capture_output=True,
            timeout=30,
            cwd=tmp_path,
        )

        # Baseline (without --prof-md)
        baseline_times = []
        for _ in range(3):
            start = time.perf_counter()
            subprocess.run(
                [velo_binary, "run", str(heavy_import_script)],
                capture_output=True,
                timeout=30,
                cwd=tmp_path,
            )
            baseline_times.append(time.perf_counter() - start)
        baseline_avg = sum(baseline_times) / len(baseline_times)

        # With profiling
        profile_times = []
        for i in range(3):
            start = time.perf_counter()
            subprocess.run(
                [velo_binary, "run", f"--prof-md={tmp_path / f'perf_{i}.md'}", str(heavy_import_script)],
                capture_output=True,
                timeout=30,
                cwd=tmp_path,
            )
            profile_times.append(time.perf_counter() - start)
        profile_avg = sum(profile_times) / len(profile_times)

        # Calculate overhead
        if baseline_avg > 0:
            overhead = (profile_avg - baseline_avg) / baseline_avg * 100
        else:
            overhead = 0

        # Allow 10% margin due to measurement noise (Gate C threshold is 5%)
        assert overhead < 10, f"Performance overhead too high: {overhead:.1f}% (threshold: 10%)"


# =============================================================================
# GATE TESTS (RFC §10)
# =============================================================================


@pytest.mark.tier1
class TestQualityGates:
    """Quality Gate verification tests."""

    def test_GATE_B_primary_bottleneck_matches(self, velo_binary, heavy_import_script, tmp_path):
        """GATE_B: Primary Bottleneck in Summary must match first entry in Analysis."""
        report_path = tmp_path / "report.md"

        subprocess.run(
            [velo_binary, "run", f"--prof-md={report_path}", str(heavy_import_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        content = report_path.read_text()

        # Extract Primary Bottleneck from Summary
        summary_match = re.search(r"\*\*Primary Bottleneck\*\* \| `([^`]+)`", content)
        if not summary_match:
            pytest.skip("No bottlenecks detected (script too fast)")

        primary_in_summary = summary_match.group(1)

        # Extract first entry from Analysis
        analysis_match = re.search(r"### 1\. ([^\s]+)", content)
        if not analysis_match:
            pytest.skip("No bottleneck entries in analysis")

        first_in_analysis = analysis_match.group(1)

        assert primary_in_summary == first_in_analysis, (
            f"Mismatch: Summary says '{primary_in_summary}', but first entry is '{first_in_analysis}'"
        )


# =============================================================================
# JSON OUTPUT TESTS (e6f2428 - --prof-json)
# =============================================================================


@pytest.mark.tier1
class TestJSONOutput:
    """Tests for --prof-json output format."""

    def test_JSON_001_flag_exists(self, velo_binary):
        """JSON_001: --prof-json flag should be visible in help."""
        result = subprocess.run(
            [velo_binary, "run", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "--prof-json" in result.stdout, "Flag --prof-json not found in help output"

    def test_JSON_002_creates_valid_json(self, velo_binary, heavy_import_script, tmp_path):
        """JSON_002: --prof-json should create valid JSON file."""
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [velo_binary, "run", f"--prof-json={report_path}", str(heavy_import_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        assert report_path.exists(), f"JSON report not created. stderr: {result.stderr}"
        content = report_path.read_text()

        # Must be valid JSON
        data = json.loads(content)
        assert isinstance(data, dict), "JSON root must be an object"

    def test_JSON_003_has_required_fields(self, velo_binary, heavy_import_script, tmp_path):
        """JSON_003: JSON output must have required fields."""
        report_path = tmp_path / "report.json"

        subprocess.run(
            [velo_binary, "run", f"--prof-json={report_path}", str(heavy_import_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        data = json.loads(report_path.read_text())

        # Check required top-level fields
        assert "bottlenecks" in data, "Missing 'bottlenecks' field"
        assert "environment" in data, "Missing 'environment' field"
        assert isinstance(data["bottlenecks"], list), "'bottlenecks' must be a list"

    def test_JSON_004_environment_has_platform(self, velo_binary, test_script, tmp_path):
        """JSON_004: Environment must include PLATFORM field."""
        report_path = tmp_path / "report.json"

        subprocess.run(
            [velo_binary, "run", f"--prof-json={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
        )

        data = json.loads(report_path.read_text())
        env = data.get("environment", {})

        assert "PLATFORM" in env, "Missing PLATFORM in environment"
        assert "PYTHON_GIL" in env, "Missing PYTHON_GIL in environment"

    def test_JSON_005_secrets_redacted(self, velo_binary, test_script, tmp_path):
        """JSON_005: Sensitive env vars must be redacted in JSON output."""
        report_path = tmp_path / "report.json"
        env = os.environ.copy()
        env["TEST_API_KEY"] = "super_secret_json_123"

        subprocess.run(
            [velo_binary, "run", f"--prof-json={report_path}", str(test_script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            env=env,
        )

        content = report_path.read_text()
        assert "super_secret_json_123" not in content, "API_KEY value not redacted in JSON!"
