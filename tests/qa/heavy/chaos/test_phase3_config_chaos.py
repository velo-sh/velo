from __future__ import annotations

"""
Velo QA: Phase 3 Config Chaos Tests (CFG-CHAOS-xxx)
====================================================
Adversarial tests targeting Zygote configuration.

Goal: Break the config parser with malformed input!
"""

import os

from phase3_harness import ZygoteTestEnv
from qa_harness import assert_no_crash, run_velo


class TestConfigChaos:
    """CFG-CHAOS-xxx: Configuration attack tests."""

    def test_cfg_chaos_001_corrupt_tool_velo(self):
        """
        CFG-CHAOS-001: [tool.velo] section contains malformed content.

        Attack: Corrupt configuration section.
        Expected: Parse error, use defaults or fail clearly.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create pyproject.toml with corrupt [tool.velo]
            pyproject = env.path / "pyproject.toml"
            pyproject.write_text("[tool.velo]\npreload = " + os.urandom(512).hex()[:100])

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should fail with parse error or use defaults
        finally:
            env.cleanup()

    def test_cfg_chaos_002_huge_preload_list(self):
        """
        CFG-CHAOS-002: Huge preload list.

        Attack: 1000 module names in preload.
        Expected: Reject or limit gracefully.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create pyproject.toml with huge preload list
            modules = ", ".join([f'"module_{i}"' for i in range(1000)])
            pyproject = env.path / "pyproject.toml"
            pyproject.write_text(f"[tool.velo]\npreload = [{modules}]\n")

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=30)

            assert_no_crash(result)
            # Should handle gracefully (limit, warn, or fail)
        finally:
            env.cleanup()

    def test_cfg_chaos_003_nonexistent_preload_module(self):
        """
        CFG-CHAOS-003: Preload non-existent module.

        Attack: Module that doesn't exist.
        Expected: Skip with warning or fail clearly.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Config with fake module in pyproject.toml
            pyproject = env.path / "pyproject.toml"
            pyproject.write_text('[tool.velo]\npreload = ["this_module_definitely_does_not_exist_xyz123"]\n')

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should skip bad module or give clear error
        finally:
            env.cleanup()

    def test_cfg_chaos_006_path_traversal_in_config(self):
        """
        CFG-CHAOS-006: Path traversal in config values.

        Attack: preload = ["../../etc/passwd"]
        Expected: Reject, no file access.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Config with path traversal in pyproject.toml
            pyproject = env.path / "pyproject.toml"
            pyproject.write_text('[tool.velo]\npreload = ["../../etc/passwd", "../../../usr/bin/python"]\n')

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should reject path traversal
        finally:
            env.cleanup()

    def test_cfg_chaos_007_negative_timeout(self):
        """
        CFG-CHAOS-007: Negative idle timeout.

        Attack: idle_timeout = -1
        Expected: Use default or reject.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            pyproject = env.path / "pyproject.toml"
            pyproject.write_text("[tool.velo]\nidle_timeout = -1\n")

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should use default or give error
        finally:
            env.cleanup()

    def test_cfg_chaos_008_zero_timeout(self):
        """
        CFG-CHAOS-008: Zero idle timeout.

        Attack: idle_timeout = 0
        Expected: Immediate exit or error.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            pyproject = env.path / "pyproject.toml"
            pyproject.write_text("[tool.velo]\nidle_timeout = 0\n")

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should either exit immediately or give error
        finally:
            env.cleanup()


class TestConfigEdgeCases:
    """Edge case tests for configuration."""

    def test_empty_tool_velo_section(self):
        """Empty [tool.velo] section should use defaults."""
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Empty [tool.velo] section
            pyproject = env.path / "pyproject.toml"
            pyproject.write_text("[tool.velo]\n")

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_valid_config_with_preload(self):
        """Valid [tool.velo] with common modules should work."""
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Valid config in pyproject.toml
            pyproject = env.path / "pyproject.toml"
            pyproject.write_text('[tool.velo]\npreload = ["os", "sys", "json"]\nidle_timeout = 300\n')

            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Should work with valid standard modules
            assert_no_crash(result)
        finally:
            env.cleanup()
