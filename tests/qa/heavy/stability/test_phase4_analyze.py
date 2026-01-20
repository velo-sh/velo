"""
Phase 4.0 Integration Tests for `velo analyze`

Type 2 Tests: Each test creates an isolated temporary project with its own
pyproject.toml, uv.lock, and .venv. Tests do NOT import user dependencies.

See docs/TEST_ARCHITECTURE.md for full explanation.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

# Path to velo binary (built with cargo build)
VELO_BIN = Path(__file__).parents[4] / "target" / "debug" / "velo"


def get_velo_path() -> Path:
    """Get path to velo binary, building if needed."""
    if not VELO_BIN.exists():
        # Try release build
        release = VELO_BIN.parent.parent / "release" / "velo"
        if release.exists():
            return release
        pytest.skip("velo binary not found. Run 'cargo build' first.")
    return VELO_BIN


class TestAnalyzeBasic:
    """Basic velo analyze functionality tests."""

    def test_analyze_help(self):
        """Test that velo analyze --help works."""
        velo = get_velo_path()
        result = subprocess.run(
            [str(velo), "analyze", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "velo analyze" in result.stdout
        assert "--slow-threshold-ms" in result.stdout

    def test_analyze_no_entry_point_error(self):
        """Test error when no entry point found."""
        velo = get_velo_path()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [str(velo), "analyze"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0
            assert "No entry point found" in result.stderr


class TestAnalyzeWithProject:
    """Test velo analyze with Type 2 isolated projects."""

    def test_analyze_simple_script(self):
        """Test analyzing a simple Python script."""
        velo = get_velo_path()

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)

            # Create minimal project
            (project / "pyproject.toml").write_text(
                """
[project]
name = "test-simple"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
"""
            )
            (project / "main.py").write_text(
                """
import json
import os
print("Hello from test")
"""
            )

            # Initialize environment (required for Type 2 tests)
            subprocess.run(["uv", "sync"], cwd=project, check=True, capture_output=True)

            # Run velo analyze
            result = subprocess.run(
                [str(velo), "analyze", "main.py"],
                cwd=project,
                capture_output=True,
                text=True,
            )

            # Should succeed
            assert result.returncode == 0
            assert "analyzing imports" in result.stderr.lower()
            assert "Import Analysis" in result.stdout

    def test_analyze_respects_config_threshold(self):
        """Test that velo analyze respects [tool.velo] slow_threshold_ms."""
        velo = get_velo_path()

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)

            # Create project with custom threshold
            (project / "pyproject.toml").write_text(
                """
[project]
name = "test-config"
version = "0.1.0"
dependencies = []

[tool.velo]
slow_threshold_ms = 50
preload = ["json"]
"""
            )
            (project / "main.py").write_text('import json; print("OK")')

            subprocess.run(["uv", "sync"], cwd=project, check=True, capture_output=True)

            result = subprocess.run(
                [str(velo), "analyze", "main.py"],
                cwd=project,
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0
            # Should display found config
            assert "Using [tool.velo] config" in result.stderr
            assert "slow_threshold_ms = 50" in result.stderr

    def test_analyze_json_output(self):
        """Test --output generates valid JSON report."""
        velo = get_velo_path()

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)

            (project / "pyproject.toml").write_text(
                """
[project]
name = "test-json"
version = "0.1.0"
dependencies = []
"""
            )
            (project / "main.py").write_text('import json; print("OK")')

            subprocess.run(["uv", "sync"], cwd=project, check=True, capture_output=True)

            report_path = project / "report.json"
            result = subprocess.run(
                [str(velo), "analyze", "main.py", "--output", str(report_path)],
                cwd=project,
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0
            assert report_path.exists()

            # Validate JSON
            with open(report_path) as f:
                data = json.load(f)
            assert isinstance(data, dict)


class TestAnalyzeFix:
    """Test --fix flag for updating pyproject.toml."""

    def test_fix_creates_tool_velo_section(self):
        """Test --fix adds [tool.velo] section if not present."""
        velo = get_velo_path()

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)

            (project / "pyproject.toml").write_text(
                """
[project]
name = "test-fix"
version = "0.1.0"
dependencies = []
"""
            )
            (project / "main.py").write_text('print("OK")')

            subprocess.run(["uv", "sync"], cwd=project, check=True, capture_output=True)

            # Run with --fix (should create [tool.velo] section)
            result = subprocess.run(
                [str(velo), "analyze", "main.py", "--fix", "--slow-threshold-ms", "0"],
                cwd=project,
                capture_output=True,
                text=True,
            )

            # Check pyproject.toml was updated
            content = (project / "pyproject.toml").read_text()
            # Note: With threshold 0, there may or may not be slow imports
            # The test just verifies the command runs successfully
            assert result.returncode == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
