"""
Velo QA: Environment Profile Unit Tests
========================================
Unit tests for velo_zygote/env_profile.py EnvProfile detection logic.

Covers:
- VELO_ENV priority (production, ci, dev)
- CI/GITHUB_ACTIONS detection
- EnvProfile derived properties (rate_limit_disabled, timeout_multiplier, etc.)
"""

import pytest
import os
import sys
from unittest.mock import patch


class TestEnvProfileDetection:
    """Tests for EnvProfile.detect() run context detection."""

    def test_VELO_ENV_production_takes_priority(self):
        """VELO_ENV=production should result in RunContext.PRODUCTION."""
        with patch.dict(os.environ, {"VELO_ENV": "production", "CI": "true"}, clear=False):
            # Re-import to trigger detection
            from importlib import reload
            import velo_zygote.env_profile as ep
            reload(ep)
            
            profile = ep.EnvProfile.detect()
            assert profile.run_context == ep.RunContext.PRODUCTION
    
    def test_VELO_ENV_prod_shorthand(self):
        """VELO_ENV=prod should also result in PRODUCTION."""
        with patch.dict(os.environ, {"VELO_ENV": "prod"}, clear=False):
            from importlib import reload
            import velo_zygote.env_profile as ep
            reload(ep)
            
            profile = ep.EnvProfile.detect()
            assert profile.run_context == ep.RunContext.PRODUCTION

    def test_CI_true_results_in_CI_context(self):
        """CI=true should result in RunContext.CI."""
        env_clean = {k: v for k, v in os.environ.items() if not k.startswith("VELO_")}
        env_clean["CI"] = "true"
        
        with patch.dict(os.environ, env_clean, clear=True):
            from importlib import reload
            import velo_zygote.env_profile as ep
            reload(ep)
            
            profile = ep.EnvProfile.detect()
            assert profile.run_context == ep.RunContext.CI

    def test_GITHUB_ACTIONS_true_results_in_CI_context(self):
        """GITHUB_ACTIONS=true should result in RunContext.CI."""
        env_clean = {k: v for k, v in os.environ.items() if not k.startswith("VELO_")}
        env_clean["GITHUB_ACTIONS"] = "true"
        
        with patch.dict(os.environ, env_clean, clear=True):
            from importlib import reload
            import velo_zygote.env_profile as ep
            reload(ep)
            
            profile = ep.EnvProfile.detect()
            assert profile.run_context == ep.RunContext.CI

    def test_VELO_ENV_ci_explicit(self):
        """VELO_ENV=ci should result in RunContext.CI."""
        with patch.dict(os.environ, {"VELO_ENV": "ci"}, clear=False):
            from importlib import reload
            import velo_zygote.env_profile as ep
            reload(ep)
            
            profile = ep.EnvProfile.detect()
            assert profile.run_context == ep.RunContext.CI

    def test_VELO_ENV_dev_explicit(self):
        """VELO_ENV=dev should result in RunContext.DEV."""
        env_clean = {k: v for k, v in os.environ.items()}
        env_clean["VELO_ENV"] = "dev"
        # Remove CI flags that would override
        env_clean.pop("CI", None)
        env_clean.pop("GITHUB_ACTIONS", None)
        
        with patch.dict(os.environ, env_clean, clear=True):
            from importlib import reload
            import velo_zygote.env_profile as ep
            reload(ep)
            
            profile = ep.EnvProfile.detect()
            assert profile.run_context == ep.RunContext.DEV

    def test_default_is_DEV(self):
        """With no env vars set, default should be DEV."""
        env_clean = {"PATH": os.environ.get("PATH", "/usr/bin")}
        
        with patch.dict(os.environ, env_clean, clear=True):
            # Also need to remove pytest from sys.modules to avoid TEST detection
            with patch.dict(sys.modules, {"pytest": None}):
                from importlib import reload
                import velo_zygote.env_profile as ep
                reload(ep)
                
                profile = ep.EnvProfile.detect()
                assert profile.run_context == ep.RunContext.DEV


class TestEnvProfileProperties:
    """Tests for EnvProfile derived properties."""

    def test_rate_limit_disabled_in_CI(self):
        """rate_limit_disabled should be True when run_context is CI."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        assert profile.rate_limit_disabled is True

    def test_rate_limit_disabled_via_env_var(self):
        """VELO_RATE_LIMIT_DISABLED=1 should disable rate limiting."""
        with patch.dict(os.environ, {"VELO_RATE_LIMIT_DISABLED": "1"}):
            from velo_zygote.env_profile import EnvProfile, RunContext, OsType
            
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.rate_limit_disabled is True

    def test_rate_limit_enabled_by_default(self):
        """Rate limiting should be enabled in DEV without override."""
        env_clean = {k: v for k, v in os.environ.items() if "RATE_LIMIT" not in k}
        
        with patch.dict(os.environ, env_clean, clear=True):
            from velo_zygote.env_profile import EnvProfile, RunContext, OsType
            
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.rate_limit_disabled is False

    def test_timeout_multiplier_default(self):
        """Default timeout multiplier should be 1.0."""
        env_clean = {k: v for k, v in os.environ.items() if "TIMEOUT" not in k}
        
        with patch.dict(os.environ, env_clean, clear=True):
            from velo_zygote.env_profile import EnvProfile, RunContext, OsType
            
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.timeout_multiplier == 1.0

    def test_timeout_multiplier_CI_default(self):
        """CI should have 6.0x timeout multiplier by default."""
        env_clean = {k: v for k, v in os.environ.items() if "TIMEOUT" not in k}
        
        with patch.dict(os.environ, env_clean, clear=True):
            from velo_zygote.env_profile import EnvProfile, RunContext, OsType
            
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
            assert profile.timeout_multiplier == 6.0

    def test_timeout_multiplier_custom(self):
        """VELO_TIMEOUT_MULTIPLIER should override default."""
        with patch.dict(os.environ, {"VELO_TIMEOUT_MULTIPLIER": "10.0"}):
            from velo_zygote.env_profile import EnvProfile, RunContext, OsType
            
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.timeout_multiplier == 10.0

    def test_allow_home_path_in_CI(self):
        """CI context should allow /home paths."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        assert profile.allow_home_path is True

    def test_allow_home_path_false_in_DEV(self):
        """DEV context should NOT allow /home paths."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
        assert profile.allow_home_path is False

    def test_strict_numa_requires_three_conditions(self):
        """strict_numa requires Linux + PRODUCTION + VELO_STRICT_NUMA=1."""
        with patch.dict(os.environ, {"VELO_STRICT_NUMA": "1"}):
            from velo_zygote.env_profile import EnvProfile, RunContext, OsType
            
            # All conditions met
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.PRODUCTION)
            assert profile.strict_numa is True
            
            # macOS - fails
            profile = EnvProfile(os_type=OsType.MACOS, run_context=RunContext.PRODUCTION)
            assert profile.strict_numa is False
            
            # Not production - fails
            profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
            assert profile.strict_numa is False

    def test_abstract_sockets_linux_only(self):
        """Abstract sockets only supported on Linux."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        linux = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
        assert linux.supports_abstract_sockets is True
        
        macos = EnvProfile(os_type=OsType.MACOS, run_context=RunContext.DEV)
        assert macos.supports_abstract_sockets is False

    def test_fd_dir_platform_specific(self):
        """fd_dir should be /dev/fd on macOS, /proc/self/fd on Linux."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        linux = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.DEV)
        assert linux.fd_dir == "/proc/self/fd"
        
        macos = EnvProfile(os_type=OsType.MACOS, run_context=RunContext.DEV)
        assert macos.fd_dir == "/dev/fd"


class TestEnvProfileDiagnostics:
    """Tests for EnvProfile diagnostic methods."""

    def test_describe_format(self):
        """describe() should return formatted string."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        desc = profile.describe()
        assert "LINUX" in desc
        assert "CI" in desc

    def test_to_dict_contains_all_properties(self):
        """to_dict() should include all key properties."""
        from velo_zygote.env_profile import EnvProfile, RunContext, OsType
        
        profile = EnvProfile(os_type=OsType.LINUX, run_context=RunContext.CI)
        d = profile.to_dict()
        
        assert "os_type" in d
        assert "run_context" in d
        assert "is_container" in d
        assert "supports_abstract_sockets" in d
        assert "rate_limit_disabled" in d
        assert "timeout_multiplier" in d
