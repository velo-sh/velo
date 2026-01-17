"""
Velo Configuration SSOT (RFC-0011)

Centralizes all configuration logic, environment variable parsing, and defaults.
Replaces ad-hoc os.environ accesses scattered across the codebase.
"""

import os
from dataclasses import dataclass, field

# Environment Profile (SSOT for all env detection)
try:
    from .env_profile import ENV_PROFILE, OsType, RunContext
except (ImportError, ValueError):
    from env_profile import ENV_PROFILE, OsType  # type: ignore[no-redef]

# Shared constants
try:
    from .constants import *
except (ImportError, ValueError):
    from constants import *  # type: ignore[no-redef]


@dataclass
class VeloConfig:
    """
    Immutable Configuration Object.

    Source Priority:
    1. CLI Arguments (passed via constructor/override)
    2. Environment Variables (VELO_*) - INJECTED BY RUST SUPERVISOR (Bridge of Truth)
    3. EnvProfile (auto-detected, immutable)
    4. Defaults (Fallback)
    """

    # Environment (derived from ENV_PROFILE)
    env: str = field(default="dev")  # dev, ci, prod

    # Security
    shield_active: bool = field(default=False)
    trusted_proxy: bool = field(default=False)
    forwarded_allow_ips: str = field(default="")
    trusted_prefixes: list[str] = field(default_factory=list)
    env_whitelist: list[str] = field(default_factory=list)
    hpc_threads: int = field(default=1)
    _blocked_paths: list[str] = field(default_factory=list)

    @property
    def blocked_paths(self) -> list[str]:
        """Validated list of blocked paths with environment adjustments."""
        return self._blocked_paths

    # Tuning
    timeout_multiplier: float = field(default=1.0)
    strict_numa: bool = field(default=False)
    max_bundle_size: int = field(default=MAX_MESSAGE_SIZE)
    socket_startup_timeout: int = field(default=SOCKET_STARTUP_TIMEOUT)
    graceful_shutdown_timeout: int = field(default=GRACEFUL_SHUTDOWN_TIMEOUT)
    host: str = field(default="127.0.0.1")
    port: int = field(default=DEFAULT_PORT)

    # Features
    preload_modules: list[str] = field(default_factory=list)

    @classmethod
    def load_from_env(cls) -> "VeloConfig":
        """
        Load configuration from environment variables.
        Uses ENV_PROFILE as SSOT for environment classification.
        """
        # RFC-0012: Boundary convergence requires VELO_ENV.
        # This is now normalized in bootstrap.py. If missing here, it's a critical failure.
        if "VELO_ENV" not in os.environ:
            raise ValueError(
                "CRITICAL: VELO_ENV not injected by Rust or Normalized by Bootstrap. Boundary convergence failed."
            )

        # Use EnvProfile for run context (replaces scattered is_ci checks)
        env_mode = ENV_PROFILE.run_context.name.lower()
        if env_mode == "test":
            env_mode = "dev"  # Map TEST -> DEV for Velo config purposes

        # Helper for ints with mandatory check
        def get_int(key: str, default: int | None = None) -> int:
            val = os.environ.get(key)
            if val is None:
                if default is not None:
                    return default
                raise ValueError(f"CRITICAL CONFIG MISSING: {key}")
            try:
                return int(val)
            except ValueError:
                if default is not None:
                    return default
                raise

        # Helper for lists
        def get_list(key: str) -> list[str]:
            val = os.environ.get(key, "")
            return [s.strip() for s in val.split(",") if s.strip()]

        instance = cls(
            env=env_mode,
            shield_active=os.environ.get("VELO_ZYGOTE_SHIELD_ACTIVE") == "1",
            trusted_proxy=os.environ.get("VELO_TRUSTED_PROXY") == "1",
            forwarded_allow_ips=os.environ.get("VELO_FORWARDED_ALLOW_IPS", ""),
            timeout_multiplier=ENV_PROFILE.timeout_multiplier,
            strict_numa=ENV_PROFILE.strict_numa,
            max_bundle_size=get_int("VELO_MAX_BUNDLE_SIZE", MAX_MESSAGE_SIZE),
            socket_startup_timeout=get_int("VELO_SOCKET_STARTUP_TIMEOUT", SOCKET_STARTUP_TIMEOUT),
            graceful_shutdown_timeout=get_int("VELO_GRACEFUL_SHUTDOWN_TIMEOUT", GRACEFUL_SHUTDOWN_TIMEOUT),
            host=os.environ.get("VELO_HOST", "127.0.0.1"),
            port=get_int("VELO_PORT", DEFAULT_PORT),
            preload_modules=get_list("VELO_PRELOAD"),
            hpc_threads=get_int("VELO_SECURITY_HPC_THREADS", 1),
        )

        # Resolve Security Matrix (Self-contained logic)
        instance.trusted_prefixes = cls._resolve_security_list(env_mode, "trusted_prefixes")
        instance.env_whitelist = cls._resolve_security_list(env_mode, "env_whitelist")

        # Resolve Blocked Paths (using EnvProfile)
        instance._blocked_paths = cls._resolve_blocked_paths()

        return instance

    @staticmethod
    def _resolve_blocked_paths() -> list[str]:
        """Resolve blocked paths using EnvProfile (Policy)."""
        # Copy base list to avoid mutation
        base = list(globals().get("DEFAULT_BLOCKED_PATHS", []))

        # Validation Fix: Allow /home in CI (where runner is in /home/runner)
        if ENV_PROFILE.allow_home_path:
            if "/home" in base:
                base.remove("/home")
        else:
            if "/home" not in base:
                base.append("/home")

        return base

    @staticmethod
    def _resolve_security_list(env_mode: str, base_key: str) -> list[str]:
        """
        Resolve security lists using hierarchical Platform x Environment matrix.
        Matches logic from RFC-0012/config.py, using EnvProfile for OS detection.
        """
        env_key = f"VELO_SECURITY_{base_key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
            return [s.strip() for s in env_val.split(",") if s.strip()]

        os_name = "macos" if ENV_PROFILE.os_type == OsType.MACOS else "linux"
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

    def validate(self) -> list[str]:
        """Verify configuration integrity. Returns list of errors."""
        errors = []
        if self.strict_numa and ENV_PROFILE.os_type != OsType.LINUX:
            errors.append("VELO_STRICT_NUMA is only supported on Linux")

        return errors


# Singleton instance for easy access
velo_config = VeloConfig.load_from_env()
