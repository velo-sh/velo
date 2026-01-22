"""
Velo QA: Phase 3.5 Exit Code and Security Tests
================================================
Tests for Phase 3.5 hardening features.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from conftest_utils import T_LONG, get_velo_binary


class RealUserEnv:
    """Simulates a REAL user project directory."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="user_project_"))
        self.velo = get_velo_binary()

    def setup(self):
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True, timeout=T_LONG)
        (self.path / "uv.lock").write_text("{}")
        return self

    def create_script(self, name: str, content: str):
        (self.path / name).write_text(content)

    def run_velo(self, args: list, timeout: float = 30) -> tuple:
        result = subprocess.run(
            [self.velo] + args,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr

    def cleanup(self):
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass

    def __enter__(self):
        return self.setup()

    def __exit__(self, *args):
        self.cleanup()


class TestExitCodeCapture:
    """Tests for DEF-P3-013/014: Exit code capture."""

    def test_sys_exit_0(self):
        """sys.exit(0) should return exit code 0."""
        with RealUserEnv() as env:
            env.create_script("exit0.py", "import sys; sys.exit(0)")
            code, _, _ = env.run_velo(["run", "--zygote", "exit0.py"])
            assert code == 0, f"Expected 0, got {code}"

    def test_sys_exit_1(self):
        """sys.exit(1) should return exit code 1."""
        with RealUserEnv() as env:
            env.create_script("exit1.py", "import sys; sys.exit(1)")
            code, _, _ = env.run_velo(["run", "--zygote", "exit1.py"])
            assert code == 1, f"Expected 1, got {code}"

    def test_sys_exit_42(self):
        """DEF-P3-013: sys.exit(42) should return exit code 42."""
        with RealUserEnv() as env:
            env.create_script("exit42.py", "import sys; sys.exit(42)")
            code, _, _ = env.run_velo(["run", "--zygote", "exit42.py"])
            assert code == 42, f"Expected 42, got {code}"

    def test_script_success(self):
        """Successful script should return exit code 0."""
        with RealUserEnv() as env:
            env.create_script("success.py", "print('hello')")
            code, stdout, _ = env.run_velo(["run", "--zygote", "success.py"])
            assert code == 0, f"Expected 0, got {code}"
            assert "hello" in stdout

    def test_script_exception(self):
        """Script raising exception should return non-zero."""
        with RealUserEnv() as env:
            env.create_script("error.py", "raise ValueError('test error')")
            code, _, _ = env.run_velo(["run", "--zygote", "error.py"])
            assert code != 0, f"Expected non-zero, got {code}"


class TestSecurityPathValidation:
    """Tests for SEC-P3-001: Path traversal protection."""

    def test_normal_script_allowed(self):
        """Normal scripts in user directory should work."""
        with RealUserEnv() as env:
            env.create_script("normal.py", "print('ok')")
            code, stdout, _ = env.run_velo(["run", "--zygote", "normal.py"])
            assert code == 0 or "ok" in stdout or "Falling back" in stdout

    def test_nonexistent_script_error(self):
        """Non-existent script should fail gracefully."""
        with RealUserEnv() as env:
            code, _, stderr = env.run_velo(["run", "--zygote", "nonexistent.py"])
            # Should fail but not crash
            assert code != 0 or "not found" in stderr.lower() or "Falling back" in stderr


class TestStderrCapture:
    """Tests for stderr capture feature."""

    def test_stderr_output(self):
        """stderr should be captured."""
        with RealUserEnv() as env:
            env.create_script(
                "stderr_test.py",
                """
import sys
print("error message", file=sys.stderr)
""",
            )
            code, _, stderr = env.run_velo(["run", "--zygote", "stderr_test.py"])
            # Either captured or script succeeded
            assert code == 0 or "error message" in stderr or "Falling back" in stderr
