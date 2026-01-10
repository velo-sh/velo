"""
Phase 5.0 Fast Loader: L0 Smoke Tests

RFC-0006 Section 5: Acceptance Criteria - L0 Smoke Tests
These tests MUST pass before any other tests run.

Test IDs:
- SMOKE-001: Bundle creation works
- SMOKE-002: velo run --fast boots
- SMOKE-003: Basic import works
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Add python/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python"))

from bundle_builder import build_from_project


# === Fixtures ===


@pytest.fixture
def simple_project(tmp_path):
    """Create minimal Python project for smoke testing."""
    # Create main.py
    main_py = tmp_path / "main.py"
    main_py.write_text(
        """
import json
print("Hello from Fast Loader!")
data = json.dumps({"status": "ok"})
print(data)
"""
    )

    # Create pyproject.toml
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "smoke-test"
version = "0.1.0"
requires-python = ">=3.11"
"""
    )

    return tmp_path


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    # Try cargo build path first
    cargo_path = (
        Path(__file__).parent.parent.parent.parent / "target" / "release" / "velo"
    )
    if cargo_path.exists():
        return str(cargo_path)

    # Try debug build
    debug_path = (
        Path(__file__).parent.parent.parent.parent / "target" / "debug" / "velo"
    )
    if debug_path.exists():
        return str(debug_path)

    # Assume in PATH
    return "velo"


def run_velo(args: list, cwd: Path, velo_binary: str, timeout: int = 30):
    """Helper to run velo command."""
    result = subprocess.run(
        [velo_binary] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def build_bundle(project_dir: Path) -> Path:
    """Build bundle using Python builder."""
    cache_dir = project_dir / ".velo" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / "bundle.veloc"
    return build_from_project(project_dir, output_path)


# === L0 Smoke Tests ===


class TestL0Smoke:
    """
    Level 0: Smoke Tests

    These are the absolute minimum tests that must pass.
    If ANY of these fail, the feature is fundamentally broken.
    """

    @pytest.mark.smoke
    def test_smoke_001_bundle_creation(self, simple_project):
        """
        SMOKE-001: Bundle creation works

        RFC-0006 Section 5: `bundle.veloc` exists after build
        """
        # Build using Python builder
        bundle_path = build_bundle(simple_project)

        # Check bundle exists
        assert bundle_path.exists(), "bundle.veloc not created"

        # Check bundle has content
        assert bundle_path.stat().st_size > 0, "bundle.veloc is empty"

        # Check magic bytes
        with open(bundle_path, "rb") as f:
            magic = f.read(4)
        assert magic == b"VELO", f"Invalid magic: {magic}"

    @pytest.mark.smoke
    def test_smoke_002_velo_run_fast_boots(self, simple_project, velo_binary):
        """
        SMOKE-002: velo run --fast boots

        RFC-0006 Section 5: Exit code 0
        """
        # First build the bundle
        build_bundle(simple_project)

        # Run with --fast
        result = run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)

        # Check exit code
        assert result.returncode == 0, f"velo run --fast failed: {result.stderr}"

        # Check output
        assert "Hello from Fast Loader!" in result.stdout, "Expected output not found"

    @pytest.mark.smoke
    def test_smoke_003_basic_import_works(self, simple_project, velo_binary):
        """
        SMOKE-003: Basic import works

        RFC-0006 Section 5: `import json` succeeds from bundle
        """
        # First build the bundle
        build_bundle(simple_project)

        # Run with --fast
        result = run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)

        # Check json module was imported and used
        assert (
            '"status": "ok"' in result.stdout or '{"status": "ok"}' in result.stdout
        ), f"json module output not found in: {result.stdout}"


# === L0 Performance Baseline ===


class TestL0PerformanceBaseline:
    """
    L0 Performance: Ensure --fast is not slower than normal

    First Principles: We test CORE FUNCTIONALITY first.
    """

    @pytest.mark.smoke
    def test_no_performance_regression(self, simple_project, velo_binary):
        """
        Verify --fast is not slower than regular run.

        Note: This is a SMOKE test, not a performance benchmark.
        We only check for obvious regressions (> 2x slower).
        """
        # Build bundle first
        build_bundle(simple_project)

        # Warm up
        run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)
        run_velo(["run", "main.py"], simple_project, velo_binary)

        # Measure --fast time
        start = time.perf_counter()
        run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)
        time_fast = time.perf_counter() - start

        # Measure normal time
        start = time.perf_counter()
        run_velo(["run", "main.py"], simple_project, velo_binary)
        time_normal = time.perf_counter() - start

        # Allow 2x margin for smoke test (not strict benchmark)
        assert (
            time_fast <= time_normal * 2
        ), f"--fast is too slow: {time_fast:.3f}s vs {time_normal:.3f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "smoke"])
