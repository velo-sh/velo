"""
RFC-0038 AI-Native Diagnostics: Core Feature Tests

Test Tiers:
- L0 (Smoke): Basic flag and file creation
- L1 (Feature): Format compliance, GFM structure
- L2 (Edge): Atomicity, Unicode, truncation

Ref: docs/qa/PHASES/RFC-0038/test-matrix.md
"""

import subprocess

import pytest


@pytest.mark.tier0
def test_L0_001_prof_md_flag_exists(velo_binary):
    """L0_001: --prof-md flag visible in help."""
    result = subprocess.run(
        [velo_binary, "run", "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert "--prof-md" in result.stdout, "Flag --prof-md not found in help"


@pytest.mark.tier0
def test_L0_002_prof_md_creates_file(velo_test_env):
    """L0_002: Report file created when specified."""
    env = velo_test_env

    # Create simple test script
    script = env.home / "test_script.py"
    script.write_text("""
import json
print("Test complete")
""")

    report_path = env.home / "report.md"

    # Run with --prof-md
    result = env.run_velo(["run", f"--prof-md={report_path}", str(script)])

    assert result.returncode == 0, f"velo run failed: {result.stderr}"
    assert report_path.exists(), f"Report not created at {report_path}"

    # Verify it's not empty
    content = report_path.read_text()
    assert len(content) > 100, "Report is too short"


@pytest.mark.tier1
def test_L1_001_version_header(velo_test_env):
    """L1_001: Version header present."""
    env = velo_test_env

    script = env.home / "test.py"
    script.write_text('print("test")')

    report = env.home / "report.md"
    result = env.run_velo(["run", f"--prof-md={report}", str(script)])

    assert result.returncode == 0
    content = report.read_text()

    # Check first line
    first_line = content.split("\n")[0]
    assert first_line.startswith("<!--"), "First line should be HTML comment"
    assert "velo:diagnostics" in first_line, "Missing velo:diagnostics marker"
    assert "v=1" in first_line, "Missing version marker"


@pytest.mark.tier1
def test_L1_002_summary_placement(velo_test_env):
    """L1_002: ## 📋 Summary appears immediately after title."""
    env = velo_test_env

    script = env.home / "test.py"
    script.write_text('import os\nprint("test")')

    report = env.home / "report.md"
    result = env.run_velo(["run", f"--prof-md={report}", str(script)])

    assert result.returncode == 0
    content = report.read_text()
    lines = content.split("\n")

    # Find title line
    title_idx = None
    for i, line in enumerate(lines):
        if line.startswith("# Velo Diagnostic Report"):
            title_idx = i
            break

    assert title_idx is not None, "Title not found"

    # Summary should be shortly after
    summary_found = False
    for i in range(title_idx, min(title_idx + 5, len(lines))):
        if "## 📋 Summary" in lines[i]:
            summary_found = True
            break

    assert summary_found, "Summary section not found near title"


@pytest.mark.tier1
def test_L1_003_hot_functions_table(velo_test_env):
    """L1_003: Hot Functions table exists."""
    env = velo_test_env

    # Script with imports
    script = env.home / "heavy.py"
    script.write_text("""
import json
import hashlib
print("done")
""")

    report = env.home / "report.md"
    result = env.run_velo(["run", f"--prof-md={report}", str(script)])

    assert result.returncode == 0
    content = report.read_text()

    assert "## 🔍 Top Bottleneck Analysis" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
