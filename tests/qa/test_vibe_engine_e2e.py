"""
Phase 8 Vibe Engine E2E Test Suite
===================================

First Principles QA: Test from USER perspective, not implementation details.

User Story:
    "As a developer, I want to edit my Python code and see instant feedback
     without restarting my application."

Test Scenarios:
1. velo run --vibe: Script hot-reload
2. velo serve --vibe: Server hot-reload
3. velo test --vibe: Test re-run on change
"""

import subprocess
import time
from pathlib import Path

import pytest

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    # Try release first, then debug
    project_root = Path(__file__).parent.parent.parent
    release = project_root / "target" / "release" / "velo"
    debug = project_root / "target" / "debug" / "velo"

    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("Velo binary not found. Run 'cargo build --release' first.")


@pytest.fixture
def temp_project(tmp_path):
    """Create a minimal Python project for testing."""
    # Create app.py
    app_py = tmp_path / "app.py"
    app_py.write_text("""
def main():
    print("Hello from Vibe!")
    return 42

if __name__ == "__main__":
    main()
""")

    # Create pyproject.toml
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""
[project]
name = "vibe-test"
version = "0.1.0"
""")

    return tmp_path


# =============================================================================
# Test: CLI Help Output
# =============================================================================


class TestVibeCliHelp:
    """Verify --vibe appears in all relevant command help."""

    def test_run_help_shows_vibe(self, velo_binary):
        """velo run --help should show --vibe option."""
        result = subprocess.run([velo_binary, "run", "--help"], capture_output=True, text=True, timeout=10)
        assert "--vibe" in result.stdout, "run command missing --vibe option"
        assert "--live" in result.stdout, "run command missing --live alias"

    def test_serve_help_shows_vibe(self, velo_binary):
        """velo serve --help should show --vibe option."""
        result = subprocess.run([velo_binary, "serve", "--help"], capture_output=True, text=True, timeout=10)
        assert "--vibe" in result.stdout, "serve command missing --vibe option"
        assert "--live" in result.stdout, "serve command missing --live alias"

    def test_test_help_shows_vibe(self, velo_binary):
        """velo test --help should show --vibe option."""
        result = subprocess.run([velo_binary, "test", "--help"], capture_output=True, text=True, timeout=10)
        assert "--vibe" in result.stdout, "test command missing --vibe option"
        assert "--live" in result.stdout, "test command missing --live alias"


# =============================================================================
# Test: Vibe Engine Activation
# =============================================================================


class TestVibeEngineActivation:
    """Verify Vibe Engine activates correctly."""

    def test_run_vibe_activates_engine(self, velo_binary, temp_project):
        """velo run --vibe should print activation message."""
        proc = subprocess.Popen(
            [velo_binary, "run", "--vibe", "app.py"],
            cwd=temp_project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            # Wait for startup message (max 5 seconds)
            output = ""
            start = time.time()
            while time.time() - start < 5:
                line = proc.stdout.readline()
                if not line:
                    break
                output += line
                if "Vibe Engine" in line:
                    break

            assert "Vibe Engine" in output, f"Expected 'Vibe Engine' in output, got: {output}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_serve_vibe_activates_engine(self, velo_binary, temp_project):
        """velo serve --vibe should print activation message."""
        # Create a minimal ASGI app
        main_py = temp_project / "main.py"
        main_py.write_text("""
async def app(scope, receive, send):
    pass
""")

        proc = subprocess.Popen(
            [velo_binary, "serve", "--vibe", "main:app"],
            cwd=temp_project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            output = ""
            start = time.time()
            while time.time() - start < 5:
                line = proc.stdout.readline()
                if not line:
                    break
                output += line
                if "Vibe Engine" in line:
                    break

            assert "Vibe Engine" in output, f"Expected 'Vibe Engine' in output, got: {output}"
            assert "Serve Mode" in output, f"Expected 'Serve Mode' in output, got: {output}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_test_vibe_activates_engine(self, velo_binary, temp_project):
        """velo test --vibe should print activation message."""
        # Create tests directory
        tests_dir = temp_project / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("""
def test_example():
    assert True
""")

        proc = subprocess.Popen(
            [velo_binary, "test", "--vibe", "tests/"],
            cwd=temp_project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            output = ""
            start = time.time()
            while time.time() - start < 5:
                line = proc.stdout.readline()
                if not line:
                    break
                output += line
                if "Vibe Engine" in line:
                    break

            assert "Vibe Engine" in output, f"Expected 'Vibe Engine' in output, got: {output}"
            assert "Test Mode" in output, f"Expected 'Test Mode' in output, got: {output}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)


# =============================================================================
# Test: --live Alias Works
# =============================================================================


class TestLiveAlias:
    """Verify --live works as alias for --vibe."""

    def test_run_live_equals_vibe(self, velo_binary, temp_project):
        """velo run --live should work same as --vibe."""
        proc = subprocess.Popen(
            [velo_binary, "run", "--live", "app.py"],
            cwd=temp_project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            output = ""
            start = time.time()
            while time.time() - start < 5:
                line = proc.stdout.readline()
                if not line:
                    break
                output += line
                if "Vibe Engine" in line:
                    break

            assert "Vibe Engine" in output, "--live should activate Vibe Engine"
        finally:
            proc.terminate()
            proc.wait(timeout=5)


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
