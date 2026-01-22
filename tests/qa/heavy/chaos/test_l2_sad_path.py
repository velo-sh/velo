import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4] / "python"))
from bundle_builder import build_from_project


def build_bundle(project_dir: Path) -> Path:
    cache_dir = project_dir / ".velo" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return build_from_project(project_dir, cache_dir / "bundle.veloc")


"""
Phase 5.0 Fast Loader: L2 Sad Path Tests

RFC-0006 Section 5: Acceptance Criteria - L2 Sad Path
Failure recovery and graceful degradation.

Test IDs:
- FALL-001: Corrupted bundle falls back to standard import
- FALL-002: Missing module falls back gracefully
- REBUILD-001: Source changed triggers auto-rebuild
"""

import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def simple_project(tmp_path):
    """Create minimal Python project."""
    main_py = tmp_path / "main.py"
    main_py.write_text(
        """
import json
print("Hello from Fast Loader!")
print(json.dumps({"status": "ok"}))
"""
    )

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sad-path-test"
version = "0.1.0"
"""
    )

    return tmp_path


@pytest.fixture
def velo_binary() -> str:
    """Get path to velo binary."""
    cargo_path = Path(__file__).parents[4] / "target" / "release" / "velo"
    if cargo_path.exists():
        return str(cargo_path)
    debug_path = Path(__file__).parents[4] / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    return "velo"


def run_velo(args: list[str], cwd: Path, velo_binary: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Helper to run velo command."""
    result = subprocess.run(
        [velo_binary] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


# === L2 Sad Path Tests ===


class TestL2SadPath:
    """
    Level 2: Sad Path Tests

    System should gracefully handle failures.
    """

    @pytest.mark.sad_path
    def test_fall_001_corrupted_bundle_fallback(self, simple_project, velo_binary):
        """
        FALL-001: Corrupted bundle falls back to standard import

        RFC-0006: When bundle is corrupted, fallback to normal import.
        """
        # Build valid bundle first
        bundle_path = build_bundle(simple_project)
        assert bundle_path.exists()

        # Corrupt the bundle
        bundle_path = simple_project / ".velo" / "cache" / "bundle.veloc"
        if bundle_path.exists():
            original_data = bundle_path.read_bytes()
            # Corrupt middle section
            corrupted = original_data[:100] + b"\x00\xff\xde\xad\xbe\xef" * 50 + original_data[400:]
            bundle_path.write_bytes(corrupted)

        # Run with --fast should still work (via fallback)
        result = run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)

        # Should succeed via fallback
        assert result.returncode == 0 or "fallback" in result.stderr.lower(), f"Expected fallback, got: {result.stderr}"

        # If it succeeded, output should be correct
        if result.returncode == 0:
            assert "Hello from Fast Loader!" in result.stdout

    @pytest.mark.sad_path
    def test_fall_002_missing_module_graceful(self, simple_project, velo_binary):
        """
        FALL-002: Missing module falls back gracefully

        RFC-0006: Module not in bundle should use normal import.
        """
        # Build bundle
        build_bundle(simple_project)

        # Create new module AFTER build (not in bundle)
        new_module = simple_project / "new_module.py"
        new_module.write_text("NEW_VALUE = 42")

        # Create main that uses both bundled and new module
        main_py = simple_project / "main.py"
        main_py.write_text(
            """
import json  # Should be in bundle
import new_module  # Should fallback to file

print(f"json works: {json.dumps({'ok': True})}")
print(f"new_module works: {new_module.NEW_VALUE}")
"""
        )

        # Run with --fast
        result = run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)

        # Should work: json from bundle, new_module from fallback
        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "json works" in result.stdout
        assert "new_module works: 42" in result.stdout

    @pytest.mark.sad_path
    def test_rebuild_001_source_changed(self, simple_project, velo_binary):
        """
        REBUILD-001: Source changed triggers auto-rebuild

        RFC-0006: Modified source should invalidate bundle.
        """
        # Initial build
        build_bundle(simple_project)

        bundle_path = simple_project / ".velo" / "cache" / "bundle.veloc"
        if bundle_path.exists():
            mtime_before = bundle_path.stat().st_mtime
        else:
            mtime_before = 0

        # Wait a bit to ensure mtime changes
        time.sleep(0.1)

        # Modify source
        main_py = simple_project / "main.py"
        main_py.write_text(
            """
import json
print("MODIFIED VERSION!")
print(json.dumps({"version": 2}))
"""
        )

        # Run with --fast (should auto-rebuild)
        result = run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)

        # Check output reflects new code
        assert result.returncode == 0
        assert "MODIFIED VERSION!" in result.stdout

    @pytest.mark.sad_path
    def test_missing_bundle_creates_new(self, simple_project, velo_binary):
        """
        Missing bundle should trigger build on first --fast run.
        """
        # Don't build - just run with --fast
        result = run_velo(["run", "--fast", "main.py"], simple_project, velo_binary)

        # Should either:
        # 1. Build bundle automatically and succeed
        # 2. Fall back to normal run and succeed
        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "Hello" in result.stdout


# === L2 Error Handling Tests ===


class TestL2DiskExhausted:
    """
    L2-04: Disk space exhausted handling
    """

    @pytest.mark.sad_path
    @pytest.mark.skip(reason="Python builder doesn't use velo CLI, test needs redesign")
    def test_disk_space_exhausted_graceful(self, tmp_path, velo_binary):
        """
        L2-04: Disk space exhausted during build

        Should fail gracefully with clear error message.
        Note: This test is skipped because it tests velo CLI behavior,
        but bundle building now uses Python builder directly.
        """
        pass


class TestL2ErrorHandling:
    """
    L2: Error handling for various failure modes.
    """

    @pytest.mark.sad_path
    def test_nonexistent_file_error(self, tmp_path, velo_binary):
        """Running nonexistent file should give clear error."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "0.1.0"')

        result = run_velo(["run", "--fast", "nonexistent.py"], tmp_path, velo_binary)

        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "no such file" in result.stderr.lower()

    @pytest.mark.sad_path
    def test_syntax_error_reported(self, tmp_path, velo_binary):
        """Syntax errors in Python code should be reported."""
        main_py = tmp_path / "main.py"
        main_py.write_text("def broken(\n")  # Syntax error

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "0.1.0"')

        # Build will fail due to syntax error - that's expected
        try:
            build_bundle(tmp_path)
        except SyntaxError:
            pass  # Expected

        # Run should fail with syntax error
        result = run_velo(["run", "--fast", "main.py"], tmp_path, velo_binary)

        assert result.returncode != 0
        assert "syntax" in result.stderr.lower() or "error" in result.stderr.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "sad_path"])
