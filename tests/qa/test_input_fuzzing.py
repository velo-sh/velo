from __future__ import annotations
"""
Velo QA: Input Fuzzing Tests (FUZZ-xxx)
=======================================
Adversarial tests with malicious/unusual input.

These tests attempt to BREAK velo by providing:
- Unusual file paths (unicode, spaces, special chars)
- Special files (/dev/null, pipes, directories)
- Path traversal attacks
- NULL byte injection

Goal: Velo should handle all edge cases without crashing.
"""

import os
import pytest
from pathlib import Path

from test_harness import (
    VeloTestEnv,
    run_velo,
    assert_no_crash,
    VELO_BINARY,
)


class TestInputFuzzingPATHS:
    """FUZZ-001 to FUZZ-003: Unusual path tests."""

    def test_fuzz_001_script_path_with_spaces(self):
        """FUZZ-001: Script path with spaces should work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create script with spaces in name
            script = env.create_script("my script.py", "print('spaces work')")
            
            result = run_velo(["run", "my script.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success, f"Spaces in path failed: {result.stderr}"
            assert "spaces work" in result.stdout
        finally:
            env.cleanup()

    def test_fuzz_002_script_path_with_unicode(self):
        """FUZZ-002: Script path with unicode should work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create script with unicode name
            script = env.create_script("测试脚本.py", "print('unicode works: 中文')")
            
            result = run_velo(["run", "测试脚本.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success, f"Unicode path failed: {result.stderr}"
        finally:
            env.cleanup()

    def test_fuzz_003_script_is_symlink(self):
        """FUZZ-003: Script that is a symlink should work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create real script and symlink to it
            real_script = env.create_script("real.py", "print('symlink works')")
            link_path = env.path / "link.py"
            link_path.symlink_to(real_script)
            
            result = run_velo(["run", "link.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
            assert "symlink works" in result.stdout
        finally:
            env.cleanup()

    def test_fuzz_010_script_without_py_extension(self):
        """FUZZ-010: Script without .py extension should work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create script without .py extension
            script = env.path / "myscript"
            script.write_text("print('no extension')")
            
            result = run_velo(["run", "myscript"], cwd=env.path)
            assert_no_crash(result)
            # Should work - Python can execute files without .py extension
        finally:
            env.cleanup()


class TestInputFuzzingSPECIAL:
    """FUZZ-004 to FUZZ-006: Special file tests."""

    def test_fuzz_004_script_is_dev_null(self):
        """FUZZ-004: /dev/null as script should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            result = run_velo(["run", "/dev/null"], cwd=env.path)
            assert_no_crash(result)
            # Empty script - might succeed (empty output) or fail gracefully
        finally:
            env.cleanup()

    def test_fuzz_005_script_is_directory(self):
        """FUZZ-005: Directory as script should fail with clear error."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            result = run_velo(["run", "/tmp"], cwd=env.path)
            assert_no_crash(result)
            assert not result.success, "Should fail for directory"
        finally:
            env.cleanup()

    def test_fuzz_006_script_is_named_pipe(self):
        """FUZZ-006: Named pipe as script should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create named pipe
            pipe_path = env.path / "pipe_script"
            os.mkfifo(str(pipe_path))
            
            # This will likely timeout since nothing is writing to the pipe
            result = run_velo(["run", "pipe_script"], cwd=env.path, timeout=3)
            assert_no_crash(result)
        finally:
            env.cleanup()


class TestInputFuzzingSECURITY:
    """FUZZ-007 to FUZZ-009: Security-related fuzzing."""

    def test_fuzz_007_very_long_path(self):
        """FUZZ-007: Very long path should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create very long filename (within filesystem limits)
            long_name = "a" * 200 + ".py"
            env.create_script(long_name, "print('long path')")
            
            result = run_velo(["run", long_name], cwd=env.path)
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()

    def test_fuzz_008_relative_path_traversal(self):
        """FUZZ-008: Path traversal attempt should be handled safely."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Try to escape with ../
            result = run_velo(
                ["run", "../../../etc/passwd"],
                cwd=env.path
            )
            assert_no_crash(result)
            # Should fail - not a Python script
            assert not result.success
        finally:
            env.cleanup()

    def test_fuzz_009_null_byte_in_path(self):
        """FUZZ-009: NULL byte in path should not cause security issues."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            # Try to inject NULL byte (Python will reject this)
            try:
                result = run_velo(
                    ["run", "test.py\x00malicious"],
                    cwd=env.path
                )
                assert_no_crash(result)
            except (ValueError, OSError):
                # Some systems reject NULL bytes before they reach velo
                pass
        finally:
            env.cleanup()


class TestInputFuzzingEMPTY:
    """Edge cases with empty/missing input."""

    def test_no_script_argument(self):
        """No script argument should show usage."""
        result = run_velo(["run"])
        assert_no_crash(result)
        assert not result.success
        assert "script" in result.stderr.lower() or "usage" in result.stderr.lower()

    def test_nonexistent_script(self):
        """Nonexistent script should fail with clear error."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            result = run_velo(["run", "does_not_exist.py"], cwd=env.path)
            assert_no_crash(result)
            assert not result.success
            assert "not found" in result.stderr.lower() or "no such" in result.stderr.lower()
        finally:
            env.cleanup()

    def test_empty_script_file(self):
        """Empty script file should work (no output)."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("empty.py", "")
            
            result = run_velo(["run", "empty.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success  # Empty script is valid Python
        finally:
            env.cleanup()
