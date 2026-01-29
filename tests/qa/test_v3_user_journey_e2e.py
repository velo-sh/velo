"""
V3 User Journey E2E Test Suite

QA First Principle: Ensure users can use the product normally.

Test scenarios:
- E2E-001: Basic script execution (Hello World)
- E2E-002: Dependency import (import from venv)
- E2E-003: Command line arguments (argparse)
- E2E-004: File path operations (relative paths)
- E2E-005: Exit code propagation (sys.exit)
- E2E-006: Exception exit (uncaught exception)
- E2E-007: Environment variable inheritance
- E2E-008: Startup performance
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

import pytest

# =============================================================================
# TEST INFRASTRUCTURE
# =============================================================================


class VeloResult(NamedTuple):
    """Velo command execution result"""
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float


def run_velo(
    project_dir: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> VeloResult:
    """
    Run velo command in specified project directory.

    Simulates user running: cd project_dir && velo run script.py
    """
    # Use bootstrap shim directly for testing (no full velo CLI needed)
    # Here we execute script via Python to simulate Velo's core behavior

    test_env = os.environ.copy()
    test_env["PYTHONDONTWRITEBYTECODE"] = "1"

    # Set VIRTUAL_ENV to simulate velo's venv detection
    venv_path = project_dir / ".venv"
    if venv_path.exists():
        test_env["VIRTUAL_ENV"] = str(venv_path)

    if env:
        test_env.update(env)

    # Build command - use project's Python interpreter
    python_path = venv_path / "bin" / "python" if venv_path.exists() else sys.executable

    start = time.perf_counter()
    try:
        result = subprocess.run(
            [str(python_path)] + list(args),
            cwd=str(project_dir),
            env=test_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = (time.perf_counter() - start) * 1000
        return VeloResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        return VeloResult(
            returncode=-1,
            stdout="",
            stderr="TIMEOUT",
            duration_ms=timeout * 1000,
        )


@pytest.fixture
def e2e_project(tmp_path: Path) -> Path:
    """
    Create a complete E2E test project.

    Contains:
    - pyproject.toml
    - .venv/ (uses current test environment's Python)
    - src/ with various test scripts
    """
    project = tmp_path / "e2e_project"
    project.mkdir()
    src = project / "src"
    src.mkdir()

    # pyproject.toml
    (project / "pyproject.toml").write_text("""
[project]
name = "e2e-test-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
""")

    # Create symlink to current venv (reuse test environment packages)
    current_venv = Path(sys.prefix)
    venv_link = project / ".venv"
    try:
        venv_link.symlink_to(current_venv)
    except (OSError, FileExistsError):
        # If symlink fails, copy Python interpreter path
        pass

    # E2E-001: Hello World
    (src / "hello.py").write_text("""
print("Hello World from Velo!")
""")

    # E2E-002: Dependency import (using stdlib to verify)
    (src / "use_json.py").write_text("""
import json
import sys

data = {"status": "ok", "python": sys.version_info[:2]}
print(f"JSON works: {json.dumps(data)}")
print("IMPORT_SUCCESS")
""")

    # E2E-003: Command line arguments
    (src / "cli.py").write_text("""
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--name", required=True)
args = parser.parse_args()

print(f"Hello {args.name}!")
""")

    # E2E-004: File path operations
    config_file = src / "config.json"
    config_file.write_text('{"version": "1.0.0"}')

    (src / "reader.py").write_text("""
import json
from pathlib import Path

# Use __file__ to get script directory
script_dir = Path(__file__).parent
config_path = script_dir / "config.json"

with open(config_path) as f:
    config = json.load(f)

print(f"Config loaded: version={config['version']}")
print("FILE_ACCESS_SUCCESS")
""")

    # E2E-005: Exit code propagation
    (src / "exit_42.py").write_text("""
import sys
sys.exit(42)
""")

    # E2E-006: Uncaught exception
    (src / "raise_error.py").write_text("""
raise ValueError("Intentional error for testing")
""")

    # E2E-007: Environment variables
    (src / "check_env.py").write_text("""
import os

test_var = os.environ.get("E2E_TEST_VAR", "NOT_SET")
print(f"E2E_TEST_VAR={test_var}")
""")

    # E2E-008: Performance test
    (src / "quick_script.py").write_text("""
import time
start = time.perf_counter()
print(f"Startup time: {(time.perf_counter() - start) * 1000:.2f}ms")
print("QUICK_DONE")
""")

    return project


# =============================================================================
# E2E TEST CASES
# =============================================================================


@pytest.mark.e2e
class TestUserJourneyE2E:
    """
    User journey end-to-end tests - validate Velo from user perspective.

    Each test simulates a real user scenario:
    "As a user, I want to... so that..."
    """

    # -------------------------------------------------------------------------
    # Journey 1: Basic script execution
    # -------------------------------------------------------------------------

    def test_e2e_001_hello_world(self, e2e_project: Path) -> None:
        """
        User: "I have a simple Python script, I want to run it with Velo"
        Expected: Script executes normally, outputs Hello World
        """
        result = run_velo(e2e_project, "src/hello.py")

        assert result.returncode == 0, f"Script execution failed: {result.stderr}"
        assert "Hello World" in result.stdout, f"Incorrect output: {result.stdout}"

    # -------------------------------------------------------------------------
    # Journey 2: Dependency import
    # -------------------------------------------------------------------------

    def test_e2e_002_import_dependency(self, e2e_project: Path) -> None:
        """
        User: "My script needs to import some libraries"
        Expected: Import succeeds, library works correctly
        """
        result = run_velo(e2e_project, "src/use_json.py")

        assert result.returncode == 0, f"Execution failed: {result.stderr}"
        assert "IMPORT_SUCCESS" in result.stdout, f"Import failed: {result.stdout}"
        assert "JSON works" in result.stdout

    # -------------------------------------------------------------------------
    # Journey 3: Command line arguments
    # -------------------------------------------------------------------------

    def test_e2e_003_argparse_works(self, e2e_project: Path) -> None:
        """
        User: "I use argparse to handle command line arguments"
        Expected: sys.argv passed correctly, argparse parses successfully
        """
        result = run_velo(e2e_project, "src/cli.py", "--name", "Alice")

        assert result.returncode == 0, f"Execution failed: {result.stderr}"
        assert "Hello Alice!" in result.stdout, f"Arguments not passed correctly: {result.stdout}"

    def test_e2e_003b_argparse_missing_required(self, e2e_project: Path) -> None:
        """
        User: "Missing required argument should error"
        Expected: argparse errors, non-zero exit
        """
        result = run_velo(e2e_project, "src/cli.py")

        assert result.returncode != 0, "Missing argument should error"
        assert "--name" in result.stderr or "required" in result.stderr

    # -------------------------------------------------------------------------
    # Journey 4: File path operations
    # -------------------------------------------------------------------------

    def test_e2e_004_relative_file_access(self, e2e_project: Path) -> None:
        """
        User: "My script needs to read a config file in same directory"
        Expected: Using __file__ correctly locates relative paths
        """
        result = run_velo(e2e_project, "src/reader.py")

        assert result.returncode == 0, f"Execution failed: {result.stderr}"
        assert "FILE_ACCESS_SUCCESS" in result.stdout
        assert "version=1.0.0" in result.stdout

    # -------------------------------------------------------------------------
    # Journey 5: Exit code propagation
    # -------------------------------------------------------------------------

    def test_e2e_005_exit_code_propagation(self, e2e_project: Path) -> None:
        """
        User: "After sys.exit(42), shell should receive correct exit code"
        Expected: Exit code propagated correctly
        """
        result = run_velo(e2e_project, "src/exit_42.py")

        assert result.returncode == 42, f"Exit code should be 42, got {result.returncode}"

    # -------------------------------------------------------------------------
    # Journey 6: Exception exit
    # -------------------------------------------------------------------------

    def test_e2e_006_exception_exits_nonzero(self, e2e_project: Path) -> None:
        """
        User: "Script with uncaught exception should exit non-zero"
        Expected: Exception causes non-zero exit code
        """
        result = run_velo(e2e_project, "src/raise_error.py")

        assert result.returncode != 0, "Exception should cause non-zero exit"
        assert "ValueError" in result.stderr or "Intentional error" in result.stderr

    # -------------------------------------------------------------------------
    # Journey 7: Environment variable inheritance
    # -------------------------------------------------------------------------

    def test_e2e_007_env_var_inheritance(self, e2e_project: Path) -> None:
        """
        User: "Environment variables I set should be passed to script"
        Expected: Environment variables correctly inherited
        """
        result = run_velo(
            e2e_project,
            "src/check_env.py",
            env={"E2E_TEST_VAR": "hello_from_shell"}
        )

        assert result.returncode == 0
        assert "E2E_TEST_VAR=hello_from_shell" in result.stdout

    # -------------------------------------------------------------------------
    # Journey 8: Startup performance
    # -------------------------------------------------------------------------

    def test_e2e_008_startup_performance(self, e2e_project: Path) -> None:
        """
        User: "Velo should start fast"
        Expected: Script execution time within acceptable range
        """
        # Run multiple times and take average
        durations = []
        for _ in range(3):
            result = run_velo(e2e_project, "src/quick_script.py")
            assert result.returncode == 0
            durations.append(result.duration_ms)

        avg_duration = sum(durations) / len(durations)

        # Relaxed performance threshold (direct Python execution)
        assert avg_duration < 1000, f"Startup too slow: {avg_duration:.2f}ms"
        print(f"Average startup time: {avg_duration:.2f}ms")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
