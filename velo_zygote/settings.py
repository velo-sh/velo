"""
Velo Configuration SSOT (RFC-0011)

Centralizes all configuration logic, environment variable parsing, and defaults.
Replaces ad-hoc os.environ accesses scattered across the codebase.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Set

# Shared constants
try:
    from .constants import *
except (ImportError, ValueError):
    from constants import *

@dataclass
class VeloConfig:
    """
    Immutable Configuration Object.
    
    Source Priority:
    1. CLI Arguments (passed via constructor/override)
    2. Environment Variables (VELO_*) - INJECTED BY RUST SUPERVISOR (Bridge of Truth)
    3. Defaults (Fallback)
    """
    
    # Environment
    env: str = field(default="dev")  # dev, ci, prod
    is_ci: bool = field(default=False)
    
    # Security
    shield_active: bool = field(default=False)
    trusted_proxy: bool = field(default=False)
    forwarded_allow_ips: str = field(default="")
    trusted_prefixes: List[str] = field(default_factory=list)
    env_whitelist: List[str] = field(default_factory=list)
    hpc_threads: int = field(default=1)
    _blocked_paths: List[str] = field(default_factory=list)

    @property
    def blocked_paths(self) -> List[str]:
        """Validated list of blocked paths with environment adjustments."""
        return self._blocked_paths

    
    # Tuning
    timeout_multiplier: float = field(default=1.0)
    strict_numa: bool = field(default=False)
    max_bundle_size: int = field(default=MAX_MESSAGE_SIZE)
    socket_startup_timeout: int = field(default=5)
    graceful_shutdown_timeout: int = field(default=30) # Default aligned with Rust (src/config.rs), but usually injected
    host: str = field(default="127.0.0.1")
    port: int = field(default=8000)
    
    # Features
    preload_modules: List[str] = field(default_factory=list)
    
    @classmethod
    def load_from_env(cls) -> 'VeloConfig':
        """Load configuration from environment variables."""
        env_mode = os.environ.get("VELO_ENV", "dev").lower()
        
        # Detect CI environment primarily via standard flags
        is_ci = (
            os.environ.get("CI") == "true" or 
            os.environ.get("GITHUB_ACTIONS") == "true" or
            env_mode == "ci"
        )
        
        # Tuning
        try:
            timeout_mult = float(os.environ.get("VELO_TIMEOUT_MULTIPLIER", "1.0"))
        except ValueError:
            timeout_mult = 1.0
            
        strict_numa = os.environ.get("VELO_STRICT_NUMA") == "1"
        
        # Security
        shield_active = os.environ.get("VELO_ZYGOTE_SHIELD_ACTIVE") == "1"
        trusted_proxy = os.environ.get("VELO_TRUSTED_PROXY") == "1"
        forwarded_ips = os.environ.get("VELO_FORWARDED_ALLOW_IPS", "")
        
        # Helper for ints
        def get_int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, str(default)))
            except ValueError:
                return default
                
        # Helper for lists
        def get_list(key: str) -> List[str]:
             val = os.environ.get(key, "")
             return [s.strip() for s in val.split(",") if s.strip()]

        instance = cls(
            env=env_mode,
            is_ci=is_ci,
            shield_active=shield_active,
            trusted_proxy=trusted_proxy,
            forwarded_allow_ips=forwarded_ips,
            timeout_multiplier=timeout_mult,
            strict_numa=strict_numa,
            max_bundle_size=get_int("VELO_MAX_BUNDLE_SIZE", 1024 * 1024 * 1024), # 1GB default
            socket_startup_timeout=get_int("VELO_SOCKET_STARTUP_TIMEOUT", 5),
            graceful_shutdown_timeout=get_int("VELO_GRACEFUL_SHUTDOWN_TIMEOUT", 30), # Fallback to 30s
            host=os.environ.get("VELO_HOST", "127.0.0.1"),
            port=get_int("VELO_PORT", 8000),
            preload_modules=get_list("VELO_PRELOAD"),
            hpc_threads=get_int("VELO_SECURITY_HPC_THREADS", 1)
        )
        
        # Resolve Security Matrix (Self-contained logic)
        instance.trusted_prefixes = cls._resolve_security_list(env_mode, "trusted_prefixes")
        instance.env_whitelist = cls._resolve_security_list(env_mode, "env_whitelist")
        
        # Resolve Blocked Paths (Phase 10.1)
        instance._blocked_paths = cls._resolve_blocked_paths(is_ci)

        return instance

    @staticmethod
    def _resolve_blocked_paths(is_ci: bool) -> List[str]:
        """Resolve blocked paths, applying CI logic (Policy)."""
        # Copy base list to avoid mutation
        base = list(globals().get("DEFAULT_BLOCKED_PATHS", []))
        
        # Validation Fix: Allow /home in GitHub Actions CI (where runner is in /home/runner)
        if is_ci:
            if "/home" in base:
                base.remove("/home")
        else:
            if "/home" not in base:
                base.append("/home")
                
        return base


    @staticmethod
    def _resolve_security_list(env_mode: str, base_key: str) -> List[str]:
        """
        Resolve security lists using hierarchical Platform x Environment matrix.
        Matches logic from RFC-0012/config.py
        """
        # We need access to constants. Since we are in settings.py, they are imported in global scope.
        # However, to avoid circular imports or issues, we assume they are present in globals().
        
        env_key = f"VELO_SECURITY_{base_key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
             return [s.strip() for s in env_val.split(",") if s.strip()]

        os_name = "macos" if sys.platform == "darwin" else "linux"
        suffix = base_key.upper()
        
        # Level 0: Global Base
        base_val = globals().get(f"SECURITY_BASE_{suffix}", "")
        
        # Level 1: OS Base
        os_base_key = f"SECURITY_{os_name.upper()}_BASE_{suffix}"
        os_base_val = globals().get(os_base_key, "").replace("${BASE}", base_val)
        
        # Level 2: OS + Env
        final_key = f"SECURITY_{os_name.upper()}_{env_mode.upper()}_{suffix}"
        fallback_key = f"SECURITY_{os_name.upper()}_DEV_{suffix}"
        
        profile_val = globals().get(final_key, globals().get(fallback_key, ""))
        final_val = profile_val.replace("${OS_BASE}", os_base_val)
        
        return [s.strip() for s in final_val.split(",") if s.strip()]

    def validate(self) -> List[str]:
        """Verify configuration integrity. Returns list of errors."""
        errors = []
        if self.strict_numa and not sys.platform.startswith("linux"):
            errors.append("VELO_STRICT_NUMA is only supported on Linux")
            
        return errors

# Singleton instance for easy access
velo_config = VeloConfig.load_from_env()
