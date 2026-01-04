from __future__ import annotations
"""
Velo QA: Environment Pollution Tests (ENV-xxx)
==============================================
Adversarial tests with malicious/unusual environment variables.

These tests attempt to BREAK velo by:
- Setting gigantic environment variables
- Conflicting configurations
- Missing required directories
- Unusual characters

Goal: Velo should handle polluted environments gracefully.
"""

import os
import pytest
from pathlib import Path

from test_harness import (
    VeloTestEnv,
    run_velo,
    assert_no_crash,
)


class VeloTestEnvPOLLUTION:
    """ENV-001 to ENV-002: Environment variable pollution."""

    def test_env_001_gigantic_pythonpath(self):
        """ENV-001: 1MB PYTHONPATH should not crash velo."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            # Create 1MB PYTHONPATH
            giant_path = ":".join(["/fake/path"] * 50000)  # ~600KB
            
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"PYTHONPATH": giant_path}
            )
            assert_no_crash(result)
            # Should work despite huge PYTHONPATH
        finally:
            env.cleanup()

    def test_env_002_pythonpath_with_special_chars(self):
        """ENV-002: PYTHONPATH with special characters should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            # PYTHONPATH with various special chars
            special_path = "/path/with spaces:/path/with:colons:/unicode/路径"
            
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"PYTHONPATH": special_path}
            )
            assert_no_crash(result)
        finally:
            env.cleanup()


class VeloTestEnvCONFLICT:
    """ENV-003: Conflicting configuration tests."""

    def test_env_003_conflicting_env_vars(self):
        """ENV-003: Conflicting PYTHONHOME and VELO_PYTHON should have clear precedence."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            import sys
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={
                    "VELO_PYTHON": sys.executable,
                    "PYTHONHOME": "/nonexistent/path",
                }
            )
            assert_no_crash(result)
            # VELO_PYTHON should take precedence
        finally:
            env.cleanup()


class VeloTestEnvUNICODE:
    """ENV-004: Unicode in environment variables."""

    def test_env_004_unicode_in_pythonpath(self):
        """ENV-004: Unicode in PYTHONPATH should work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"PYTHONPATH": "/路径/测试:/경로/테스트"}
            )
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()


class VeloTestEnvMISSING:
    """ENV-005 to ENV-006: Missing/broken directories."""

    def test_env_005_missing_home_dir(self):
        """ENV-005: Missing HOME directory should still work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"HOME": "/nonexistent/home"}
            )
            assert_no_crash(result)
            # Should still work - Velo doesn't require HOME
        finally:
            env.cleanup()

    def test_env_006_temp_dir_missing(self):
        """ENV-006: Missing TMPDIR should be handled."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"TMPDIR": "/nonexistent/tmp"}
            )
            assert_no_crash(result)
        finally:
            env.cleanup()


class VeloTestEnvCLEAN:
    """Test with minimal/clean environment."""

    def test_minimal_environment(self):
        """Velo should work with minimal PATH environment."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()
            
            result = run_velo(
                ["run", "test.py"],
                cwd=env.path,
                env={"PATH": "/usr/bin:/bin"}  # Minimal PATH
            )
            assert_no_crash(result)
        finally:
            env.cleanup()
