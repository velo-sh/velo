"""
Phase 5.0 Fast Loader: CLI Bundle Tests

Tests for:
- velo bundle inspect
- velo run --fast

These tests verify the Rust CLI commands work correctly.
"""

import subprocess
import sys
from pathlib import Path

import pytest


# Add python/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python"))


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    workspace = Path(__file__).parent.parent.parent.parent
    release = workspace / "target" / "release" / "velo"
    debug = workspace / "target" / "debug" / "velo"

    if release.exists():
        return str(release)
    if debug.exists():
        return str(debug)
    return "velo"


@pytest.fixture
def test_bundle(tmp_path):
    """Create a test bundle using bundle_builder."""
    from bundle_builder import VeloBundleBuilder
    import marshal

    builder = VeloBundleBuilder()

    # Add test modules
    code1 = compile("VALUE = 42", "<test>", "exec")
    builder.add_code("test_module", marshal.dumps(code1))

    code2 = compile("MSG = 'hello'", "<test>", "exec")
    builder.add_code("test_package", marshal.dumps(code2), is_package=True)

    output = tmp_path / "test.veloc"
    builder.build(output)

    return output


@pytest.fixture
def test_project(tmp_path):
    """Create a test project with bundle."""
    # Create project structure
    (tmp_path / "main.py").write_text('print("Hello from bundle!")')
    (tmp_path / "mymodule.py").write_text("VALUE = 42")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"'
    )

    # Create cache directory
    cache_dir = tmp_path / ".velo" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Build bundle using Python builder
    from bundle_builder import build_from_project

    build_from_project(tmp_path, cache_dir / "bundle.veloc")

    return tmp_path


class TestBundleInspect:
    """
    Tests for: velo bundle inspect <path>

    RFC-0006 Phase 5.0.3: CLI inspection tool
    """

    @pytest.mark.cli
    def test_bundle_inspect_basic(self, velo_binary, test_bundle):
        """
        CLI-001: velo bundle inspect shows bundle info
        """
        result = subprocess.run(
            [velo_binary, "bundle", "inspect", str(test_bundle)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should succeed
        assert result.returncode == 0, f"Failed: {result.stderr}"

        # Should show basic info
        assert "VELO" in result.stdout
        assert "Modules" in result.stdout

    @pytest.mark.cli
    def test_bundle_inspect_verify(self, velo_binary, test_bundle):
        """
        CLI-002: velo bundle inspect --verify checks integrity
        """
        result = subprocess.run(
            [velo_binary, "bundle", "inspect", str(test_bundle), "--verify"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        # Should show verification result
        assert "Verified" in result.stdout or "Integrity" in result.stdout

    @pytest.mark.cli
    def test_bundle_inspect_modules(self, velo_binary, test_bundle):
        """
        CLI-003: velo bundle inspect --modules lists all modules
        """
        result = subprocess.run(
            [velo_binary, "bundle", "inspect", str(test_bundle), "--modules"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        assert "test_module" in result.stdout
        assert "test_package" in result.stdout

    @pytest.mark.cli
    def test_bundle_inspect_json(self, velo_binary, test_bundle):
        """
        CLI-004: velo bundle inspect --json outputs JSON
        """
        result = subprocess.run(
            [velo_binary, "bundle", "inspect", str(test_bundle), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0

        # Should be valid JSON
        import json

        data = json.loads(result.stdout)
        assert data["magic"] == "VELO"
        assert data["module_count"] >= 2

    @pytest.mark.cli
    def test_bundle_inspect_not_found(self, velo_binary, tmp_path):
        """
        CLI-005: velo bundle inspect handles missing file
        """
        result = subprocess.run(
            [velo_binary, "bundle", "inspect", str(tmp_path / "nonexistent.veloc")],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


class TestRunFast:
    """
    Tests for: velo run --fast <script.py>

    RFC-0006: Fast loader mode
    """

    @pytest.mark.cli
    def test_run_fast_with_bundle(self, velo_binary, test_project):
        """
        CLI-006: velo run --fast works with bundle
        """
        result = subprocess.run(
            [velo_binary, "run", "--fast", "main.py"],
            cwd=test_project,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should succeed
        assert result.returncode == 0, f"Failed: {result.stderr}"

        # Should show fast loader message
        assert "Fast" in result.stderr or "⚡" in result.stderr

        # Should run script
        assert "Hello from bundle!" in result.stdout

    @pytest.mark.cli
    def test_run_fast_without_bundle_fallback(self, velo_binary, tmp_path):
        """
        CLI-007: velo run --fast falls back without bundle
        """
        # Create project without bundle
        (tmp_path / "main.py").write_text('print("Fallback works!")')
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"'
        )

        result = subprocess.run(
            [velo_binary, "run", "--fast", "main.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should still succeed via fallback
        if result.returncode == 0:
            assert "Fallback works!" in result.stdout
        else:
            # Fallback message should appear
            assert "fallback" in result.stderr.lower() or "No bundle" in result.stderr

    @pytest.mark.cli
    def test_run_fast_imports_from_bundle(self, velo_binary, test_project):
        """
        CLI-008: velo run --fast imports modules from bundle
        """
        # Modify main.py to import from bundle
        (test_project / "main.py").write_text(
            """
import mymodule
print(f"Value from bundle: {mymodule.VALUE}")
"""
        )

        result = subprocess.run(
            [velo_binary, "run", "--fast", "main.py"],
            cwd=test_project,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "Value from bundle: 42" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
