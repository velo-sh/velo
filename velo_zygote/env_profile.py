"""
Velo Environment Profile (RFC-0012 Phase 11.4)

Self-describing, immutable environment detection following First Principles.
Eliminates scattered is_ci checks and ad-hoc platform sniffing.

Design:
    - All environment detection happens ONCE at module import.
    - The resulting EnvProfile is frozen (immutable).
    - Downstream code depends only on EnvProfile properties.
    - No monkey-patching, no scattered os.environ checks.
"""

import os
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class OsType(Enum):
    """Operating System classification."""

    MACOS = auto()
    LINUX = auto()
    WINDOWS = auto()
    UNKNOWN = auto()


class RunContext(Enum):
    """Execution context classification."""

    DEV = auto()  # Local development
    CI = auto()  # Continuous Integration (GitHub Actions, etc.)
    PRODUCTION = auto()  # Production deployment
    TEST = auto()  # Unit/integration test harness


@dataclass(frozen=True)
class EnvProfile:
    """
    Self-describing, immutable environment profile.

    This is the SINGLE SOURCE OF TRUTH for all environment-related decisions.
    Replaces scattered checks like:
        - os.environ.get("CI") == "true"
        - sys.platform == "darwin"
        - velo_config.is_ci
    """

    os_type: OsType
    run_context: RunContext

    # Raw values for diagnostics
    _velo_env_raw: Optional[str] = None
    _ci_raw: Optional[str] = None
    _github_actions_raw: Optional[str] = None

    # --- Derived Properties (Behavior Matrix) ---

    @property
    def is_container(self) -> bool:
        """True if running inside a Docker container."""
        return os.path.exists("/.dockerenv") or os.environ.get("container") == "docker"

    @property
    def supports_abstract_sockets(self) -> bool:
        """True if the OS supports Linux abstract namespace sockets."""
        return self.os_type == OsType.LINUX

    @property
    def rate_limit_disabled(self) -> bool:
        """True if rate limiting should be disabled (e.g., in CI)."""
        return (
            self.run_context == RunContext.CI
            or os.environ.get("VELO_RATE_LIMIT_DISABLED") == "1"
        )

    @property
    def strict_numa(self) -> bool:
        """True if strict NUMA binding should be enforced."""
        return (
            self.os_type == OsType.LINUX
            and self.run_context == RunContext.PRODUCTION
            and os.environ.get("VELO_STRICT_NUMA") == "1"
        )

    @property
    def allow_home_path(self) -> bool:
        """True if /home should be allowed in path validation (e.g., CI runners live in /home)."""
        return self.run_context == RunContext.CI

    @property
    def fd_dir(self) -> str:
        """File descriptor directory path for this OS."""
        if self.os_type == OsType.MACOS:
            return "/dev/fd"
        return "/proc/self/fd"

    @property
    def timeout_multiplier(self) -> float:
        """Timeout scaling factor for slow environments."""
        if self.run_context == RunContext.CI:
            return float(os.environ.get("VELO_TIMEOUT_MULTIPLIER", "6.0"))
        return float(os.environ.get("VELO_TIMEOUT_MULTIPLIER", "1.0"))

    # --- Self-Description ---

    def describe(self) -> str:
        """Human-readable description for startup banner."""
        ctx = self.run_context.name
        os_name = self.os_type.name
        container_tag = " (container)" if self.is_container else ""
        return f"{os_name}/{ctx}{container_tag}"

    def to_dict(self) -> dict:
        """Serializable representation for diagnostics."""
        return {
            "os_type": self.os_type.name,
            "run_context": self.run_context.name,
            "is_container": self.is_container,
            "supports_abstract_sockets": self.supports_abstract_sockets,
            "rate_limit_disabled": self.rate_limit_disabled,
            "strict_numa": self.strict_numa,
            "allow_home_path": self.allow_home_path,
            "timeout_multiplier": self.timeout_multiplier,
            "_velo_env_raw": self._velo_env_raw,
            "_ci_raw": self._ci_raw,
        }

    # --- Detection (SSOT Entry Point) ---

    @classmethod
    def detect(cls) -> "EnvProfile":
        """
        Detect environment profile from system state.

        This is the ONLY place where environment sniffing happens.
        Call this once at startup, then use the resulting profile everywhere.
        """
        # 1. OS Type Detection
        if sys.platform == "darwin":
            os_type = OsType.MACOS
        elif sys.platform == "win32":
            os_type = OsType.WINDOWS
        elif sys.platform.startswith("linux"):
            os_type = OsType.LINUX
        else:
            os_type = OsType.UNKNOWN

        # 2. Run Context Detection (Priority Order)
        # RFC-0012: Surgical Environment Management
        velo_env = os.environ.get("VELO_ENV", "").lower()
        ci_flag = os.environ.get("CI", "").lower()
        gh_actions = os.environ.get("GITHUB_ACTIONS", "").lower()

        # Priority 1: Mandatory Production Override
        if velo_env in ("production", "prod"):
            run_context = RunContext.PRODUCTION

        # Priority 2: Implicit CI detection (GitHub Actions, etc.)
        # This takes precedence over VELO_ENV="dev" to allow /home paths in CI
        elif ci_flag == "true" or gh_actions == "true" or velo_env == "ci":
            run_context = RunContext.CI

        # Priority 3: Explicit VELO_ENV="dev"
        elif velo_env == "dev":
            run_context = RunContext.DEV

        # Priority 4: Pytest detection (only if no explicit VELO_ENV)
        elif "pytest" in sys.modules and not velo_env:
            run_context = RunContext.TEST

        else:
            run_context = RunContext.DEV

        return cls(
            os_type=os_type,
            run_context=run_context,
            _velo_env_raw=velo_env or None,
            _ci_raw=ci_flag or None,
            _github_actions_raw=gh_actions or None,
        )


# --- Module-Level Singleton ---
# Detected once at import, immutable thereafter.
ENV_PROFILE = EnvProfile.detect()
