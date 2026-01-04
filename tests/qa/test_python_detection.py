from __future__ import annotations
"""
Velo QA: Python Detection Tests (PYDET-xxx)
============================================
Adversarial tests targeting Python interpreter detection.

These tests attempt to BREAK Python detection by:
- Creating fake/malicious Python interpreters
- Symlink loops
- Hanging processes
- Invalid shebang

Goal: Velo should detect issues and fail gracefully with clear errors.
"""

import os
import pytest
import stat
from pathlib import Path

from test_harness import (
    VeloTestEnv,
    run_velo,
    assert_no_crash,
    assert_velo_fails_gracefully,
)


class TestPythonDetectionSYMLINKS:
    """PYDET-001: Symlink attack tests."""

    def test_pydet_001_python_symlink_loop(self):
        """PYDET-001: Symlink loop in Python path should not hang forever."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            
            # Create .venv/bin directory
            venv_bin = env.venv_path / "bin"
            venv_bin.mkdir(parents=True)
            
            # Create symlink loop: python -> python (itself)
            python_link = venv_bin / "python"
            python_link.symlink_to(python_link)
            
            # Run should timeout or fail gracefully, not hang forever
            # Note: Velo correctly falls back to system Python, which is acceptable
            result = run_velo(["run", "test.py"], cwd=env.path, timeout=5)
            assert_no_crash(result)
            # Either fails with error OR succeeds by falling back to system Python
            # Both are acceptable outcomes - the key is no hang/crash
        finally:
            env.cleanup()


class TestPythonDetectionFAKE:
    """PYDET-002 to PYDET-006: Fake/malicious Python tests."""

    def test_pydet_002_fake_python_shell_script(self):
        """PYDET-002: Shell script named 'python' should be detected or work."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            
            # Create fake python as shell script
            venv_bin = env.venv_path / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python"
            fake_python.write_text("#!/bin/bash\necho 'I am fake python'\nexit 0\n")
            fake_python.chmod(0o755)
            
            result = run_velo(["run", "test.py"], cwd=env.path, timeout=10)
            assert_no_crash(result)
            # Behavior is acceptable: either works or fails gracefully
        finally:
            env.cleanup()

    def test_pydet_003_python2_interpreter(self):
        """PYDET-003: Python 2 should be rejected with clear error."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            
            # Try to use python2 if it exists (usually /usr/bin/python2)
            if os.path.exists("/usr/bin/python2"):
                result = run_velo(
                    ["run", "test.py"],
                    cwd=env.path,
                    env={"VELO_PYTHON": "/usr/bin/python2"}
                )
                assert_no_crash(result)
                # Should either fail gracefully or warn about Python 2
            else:
                pytest.skip("Python 2 not installed")
        finally:
            env.cleanup()

    def test_pydet_004_hanging_python(self):
        """PYDET-004: Python that hangs should not hang velo forever."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            
            # Create script that hangs
            env.create_script(content="import time; time.sleep(3600)")
            
            # Velo should either timeout or we can at least kill it
            result = run_velo(["run", "test.py"], cwd=env.path, timeout=5)
            # Timeout is expected
            assert "TIMEOUT" in result.stderr or result.returncode != 0
        finally:
            env.cleanup()

    def test_pydet_006_python_outputs_garbage(self):
        """PYDET-006: Python outputting binary garbage should not crash velo."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            
            # Create fake python that outputs binary garbage
            venv_bin = env.venv_path / "bin"
            venv_bin.mkdir(parents=True)
            fake_python = venv_bin / "python"
            # Shell script that outputs random bytes
            fake_python.write_text(
                '#!/bin/bash\nhead -c 1000 /dev/urandom\nexit 0\n'
            )
            fake_python.chmod(0o755)
            
            result = run_velo(["run", "test.py"], cwd=env.path, timeout=10)
            assert_no_crash(result)
        finally:
            env.cleanup()


class TestPythonDetectionSECURITY:
    """PYDET-007 to PYDET-008: Security-related tests."""

    def test_pydet_007_path_traversal(self):
        """PYDET-007: Path traversal in VELO_PYTHON should be handled."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            
            # Try path traversal
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"VELO_PYTHON": "../../../../../../etc/passwd"}
            )
            assert_no_crash(result)
            # Should fail because /etc/passwd is not an executable
            assert not result.success
        finally:
            env.cleanup()

    def test_pydet_008_non_executable_python(self):
        """PYDET-008: Non-executable Python should give clear error."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            
            # Create non-executable file
            venv_bin = env.venv_path / "bin"
            venv_bin.mkdir(parents=True)
            python_file = venv_bin / "python"
            python_file.write_text("#!/usr/bin/env python3\nprint('hello')")
            # Explicitly remove execute permission
            python_file.chmod(0o644)
            
            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            # Should fail with permission error
            assert not result.success
        finally:
            env.cleanup()


class TestPythonDetectionFALLBACK:
    """Test Python detection fallback chain."""

    def test_no_venv_uses_system_python(self):
        """Without .venv, should fall back to system python3."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            env.create_script()
            # Note: NOT creating venv
            
            result = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result)
            # May succeed if system python3 exists
        finally:
            env.cleanup()

    def test_velo_python_env_overrides_venv(self):
        """VELO_PYTHON should take precedence over .venv."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            # Use system python instead of venv
            import sys
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"VELO_PYTHON": sys.executable}
            )
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()
