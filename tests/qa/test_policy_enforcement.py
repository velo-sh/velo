"""
QA Policy Enforcement Tests

These tests enforce P0 QA policies. They MUST FAIL if policies are violated.
"""

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestP0PolicyEnforcement:
    """P0 policies that MUST be enforced - violations = FAIL"""

    def test_P0_001_zero_mock_policy(self):
        """
        P0: Magic-Mock is BANNED in tests/qa/

        RFC-0012 Zero-Mock Policy requires all QA tests to use real objects
        or minimal Mock(), never the 'Magic' variant.
        """
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "from unittest.mock import MagicMock", "tests/qa/"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        if result.returncode == 0:
            # Filter out this file and comments
            lines = [l for l in result.stdout.strip().split("\n") if "test_policy_enforcement.py" not in l]
            if lines:
                pytest.fail(
                    "P0 VIOLATION: MagicMock import detected!\\n"
                    "RFC-0012 requires Zero-Mock.\\n"
                    "Violations:\\n" + "\\n".join(lines)
                )

    def test_P0_002_no_hardcoded_tmp_in_src(self):
        """
        P0: No hardcoded '/tmp' string literals in src/ (excluding tests)

        RFC-0012 Path Sovereignty requires all paths go through VeloPaths.
        """
        result = subprocess.run(
            ["grep", "-rn", '"/tmp"', "src/"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\\n")
            # Filter out test code and comments
            violations = [l for l in lines if "#[test]" not in l and "// " not in l and "mod tests" not in l]
            if violations:
                pytest.fail("P0 VIOLATION: Hardcoded /tmp found!\\nViolations:\\n" + "\\n".join(violations[:10]))
