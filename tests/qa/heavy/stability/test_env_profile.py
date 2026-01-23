"""
Velo QA: Environment Profile Unit Tests
========================================
Fast unit tests for velo_zygote/env_profile.py EnvProfile properties.

Note: Detection tests that require module reload are slow and skipped.
These tests focus on EnvProfile property behavior which is fast.
"""

import os
from unittest.mock import patch

from velo_zygote.env_profile import EnvProfile, OsType, RunContext


class TestEnvProfileProperties:
    """Fast tests for EnvProfile derived properties (no module reload)."""

    def test_rate_limit_disabled_in_CI(self):
        """rate_limit_disabled should be True when run_context is CI."""
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        assert profile.rate_limit_disabled is True

    def test_rate_limit_disabled_via_env_var(self):
        """VELO_RATE_LIMIT_DISABLED=1 should disable rate limiting."""
        with patch.dict(os.environ, {"VELO_RATE_LIMIT_DISABLED": "1"}):
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.rate_limit_disabled is True

    def test_rate_limit_enabled_by_default(self):
        """Rate limiting should be enabled in DEV without override."""
        env_clean = {k: v for k, v in os.environ.items() if "RATE_LIMIT" not in k}
        with patch.dict(os.environ, env_clean, clear=True):
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.rate_limit_disabled is False

    def test_timeout_multiplier_default_DEV(self):
        """Default timeout multiplier in DEV should be 1.0."""
        env_clean = {k: v for k, v in os.environ.items() if "TIMEOUT" not in k}
        with patch.dict(os.environ, env_clean, clear=True):
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.timeout_multiplier == 1.0

    def test_timeout_multiplier_CI_default(self):
        """CI should have 6.0x timeout multiplier by default."""
        env_clean = {k: v for k, v in os.environ.items() if "TIMEOUT" not in k}
        with patch.dict(os.environ, env_clean, clear=True):
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
            assert profile.timeout_multiplier == 6.0

    def test_timeout_multiplier_custom(self):
        """VELO_TIMEOUT_MULTIPLIER should override default."""
        with patch.dict(os.environ, {"VELO_TIMEOUT_MULTIPLIER": "10.0"}):
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.timeout_multiplier == 10.0

    def test_allow_home_path_in_CI(self):
        """CI context should allow /home paths."""
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        assert profile.allow_home_path is True

    def test_allow_home_path_false_in_DEV(self):
        """DEV context should NOT allow /home paths."""
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
        assert profile.allow_home_path is False

    def test_strict_numa_requires_linux_production_env(self):
        """strict_numa requires Linux + PRODUCTION + VELO_STRICT_NUMA=1."""
        with patch.dict(os.environ, {"VELO_STRICT_NUMA": "1"}):
            # All conditions met: Linux + PRODUCTION + env var
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.PRODUCTION)
            assert profile.strict_numa is True

            # macOS - fails (Linux only)
            profile = EnvProfile(os_type=OsType.MACOS, run_context=RunContext.PRODUCTION)
            assert profile.strict_numa is False

            # Not production - fails
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.strict_numa is False

    def test_abstract_sockets_linux_only(self):
        """Abstract sockets only supported on Linux."""
        linux = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
        assert linux.supports_abstract_sockets is True

        macos = EnvProfile(os_type=OsType.MACOS, run_context=RunContext.DEV)
        assert macos.supports_abstract_sockets is False

    def test_fd_dir_platform_specific(self):
        """fd_dir should be /dev/fd on macOS, /proc/self/fd on Linux."""
        linux = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
        assert linux.fd_dir == "/proc/self/fd"

        macos = EnvProfile(os_type=OsType.MACOS, run_context=RunContext.DEV)
        assert macos.fd_dir == "/dev/fd"


class TestEnvProfileDiagnostics:
    """Tests for EnvProfile diagnostic methods."""

    def test_describe_format(self):
        """describe() should return OS/Context string."""
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        desc = profile.describe()
        assert "LINUX" in desc
        assert "CI" in desc

    def test_to_dict_contains_all_properties(self):
        """to_dict() should include all key properties."""
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        d = profile.to_dict()

        assert "os_type" in d
        assert "run_context" in d
        assert "is_container" in d
        assert "supports_abstract_sockets" in d
        assert "rate_limit_disabled" in d
        assert "timeout_multiplier" in d


class TestEnvProfileDetection:
    """Tests for EnvProfile.detect() - uses static analysis, no reload."""

    def test_detect_returns_valid_profile(self):
        """EnvProfile.detect() should return a valid profile."""
        profile = EnvProfile.detect()
        assert profile.os_type in OsType
        assert profile.run_context in RunContext

    def test_detect_captures_raw_values(self):
        """detect() should capture raw env var values for diagnostics."""
        profile = EnvProfile.detect()
        # Should have diagnostic fields
        assert hasattr(profile, "_velo_env_raw")
        assert hasattr(profile, "_ci_raw")


class TestEnvProfilePriority:
    """Subprocess-based tests for VELO_ENV/CI detection priority.

    These tests run in isolated processes to avoid slow module reloads.
    Each test spawns a Python subprocess with specific env vars.
    """

    def _run_detect(self, env_vars: dict[str, str]) -> str:
        """Run EnvProfile.detect() in subprocess and return run_context name."""
        import subprocess
        import sys

        code = """
import sys; sys.path.insert(0, '.')
from velo_zygote.env_profile import EnvProfile
print(EnvProfile.detect().run_context.name)
"""
        env = os.environ.copy()
        # Clear relevant vars first
        for k in list(env.keys()):
            if k.startswith("VELO_") or k in ("CI", "GITHUB_ACTIONS"):
                del env[k]
        # Apply test env vars
        env.update(env_vars)

        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=5)
        return result.stdout.strip()

    def test_VELO_ENV_production_highest_priority(self):
        """VELO_ENV=production should override even CI=true."""
        ctx = self._run_detect({"VELO_ENV": "production", "CI": "true"})
        assert ctx == "PRODUCTION"

    def test_VELO_ENV_prod_shorthand(self):
        """VELO_ENV=prod should also result in PRODUCTION."""
        ctx = self._run_detect({"VELO_ENV": "prod"})
        assert ctx == "PRODUCTION"

    def test_CI_true_detects_CI_context(self):
        """CI=true should result in CI context."""
        ctx = self._run_detect({"CI": "true"})
        assert ctx == "CI"

    def test_GITHUB_ACTIONS_true_detects_CI_context(self):
        """GITHUB_ACTIONS=true should result in CI context."""
        ctx = self._run_detect({"GITHUB_ACTIONS": "true"})
        assert ctx == "CI"

    def test_VELO_ENV_ci_explicit(self):
        """VELO_ENV=ci should result in CI context."""
        ctx = self._run_detect({"VELO_ENV": "ci"})
        assert ctx == "CI"

    def test_VELO_ENV_dev_without_CI_flags(self):
        """VELO_ENV=dev without CI flags should result in DEV."""
        ctx = self._run_detect({"VELO_ENV": "dev"})
        assert ctx == "DEV"

    def test_default_is_DEV(self):
        """With no relevant env vars, default should be DEV."""
        ctx = self._run_detect({})
        assert ctx == "DEV"
