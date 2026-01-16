"""
RFC-0020: Zygote Observability - Pre-Flight Checks
"""

import os
import sys
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path

# Internal imports
try:
    # Rule 1: Bootstrap MUST run before anything else to normalize env
    from . import bootstrap

    bootstrap.initialize()

    from .env_profile import ENV_PROFILE, RunContext, OsType
    from .v_shield import ImportShield, PathValidator
    from .settings import velo_config
except (ImportError, ValueError):
    # Fallback for direct execution if needed
    import bootstrap

    bootstrap.initialize()

    from env_profile import ENV_PROFILE, RunContext, OsType
    from v_shield import ImportShield, PathValidator
    from settings import velo_config


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class PreflightResult:
    checks: List[CheckResult]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


class PreflightCheck:
    """
    Diagnostic suite to verify Zygote operational environment.
    Designed to fail fast and provide actionable error messages.
    """

    def run_all(self, verbose: bool = False) -> PreflightResult:
        results = []

        # 1. Environment Detection
        results.append(self._check_env_profile())

        # 2. Security Shield
        results.append(self._check_shield_status())

        # 3. Path Validation
        results.append(self._check_paths())

        return PreflightResult(checks=results)

    def _check_env_profile(self) -> CheckResult:
        """Verify that the environment profile detects the correct context."""
        try:
            # Check for critical specific flags
            is_ci_env = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))

            # Logic: If CI env vars are present, we MUST detect RunContext.CI
            context_match = True
            error_msg = None

            if is_ci_env and ENV_PROFILE.run_context != RunContext.CI:
                context_match = False
                error_msg = (
                    f"mismatch: Environment vars suggest CI ({is_ci_env}), "
                    f"but detected {ENV_PROFILE.run_context.name}"
                )

            return CheckResult(
                name="Environment Detection",
                passed=context_match,
                details={
                    "os_type": ENV_PROFILE.os_type.name,
                    "run_context": ENV_PROFILE.run_context.name,
                    "allow_home_path": ENV_PROFILE.allow_home_path,
                    "ci_env_present": is_ci_env,
                },
                error=error_msg,
            )
        except Exception as e:
            return CheckResult("Environment Detection", False, error=str(e))

    def _check_shield_status(self) -> CheckResult:
        """Verify ImportShield status and blocked paths configuration."""
        try:
            # Check if shield is currently active (should be inactive during preflight usually)
            # Accessing protected member _active for diagnostic purpose
            is_active = getattr(ImportShield, "_active", False)

            # Check blocked paths
            blocked = velo_config.blocked_paths
            home = str(Path.home())

            # Logic: In CI, /home should NOT be blocked
            home_blocked = any(home.startswith(b) for b in blocked)

            passed = True
            issues = []

            if ENV_PROFILE.run_context == RunContext.CI and home_blocked:
                passed = False
                issues.append(
                    f"CI Context but HOME ({home}) is blocked by rules: {blocked}"
                )

            return CheckResult(
                name="Security Shield Status",
                passed=passed,
                details={
                    "shield_active": is_active,
                    "blocked_paths_count": len(blocked),
                    "home_path": home,
                    "home_blocked": home_blocked,
                },
                error="; ".join(issues) if issues else None,
            )
        except Exception as e:
            return CheckResult("Security Shield Status", False, error=str(e))

    def _check_paths(self) -> CheckResult:
        """Verify critical paths are valid and accessible."""
        try:
            passed = True
            issues = []
            checked_paths = {}

            # 1. worker_launcher.py
            try:
                launcher_path = Path(__file__).parent / "worker_launcher.py"
                is_valid, reason = PathValidator.validate(str(launcher_path))
                checked_paths["worker_launcher"] = {
                    "path": str(launcher_path),
                    "valid": is_valid,
                    "reason": reason,
                }
                if not is_valid:
                    passed = False
                    issues.append(f"worker_launcher.py invalid: {reason}")
            except Exception as e:
                passed = False
                issues.append(f"Failed to check worker_launcher: {e}")

            # 2. Python Binary
            py_bin = sys.executable
            checked_paths["python_binary"] = str(py_bin)
            if not os.access(py_bin, os.X_OK):
                passed = False
                issues.append(f"Python binary not executable: {py_bin}")

            return CheckResult(
                name="Path Validation",
                passed=passed,
                details=checked_paths,
                error="; ".join(issues) if issues else None,
            )
        except Exception as e:
            return CheckResult("Path Validation", False, error=str(e))


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Velo Zygote Pre-Flight Check")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    checker = PreflightCheck()
    result = checker.run_all(verbose=args.verbose)

    if args.json:
        # manual serialization for clean output
        out = {
            "all_passed": result.all_passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "details": c.details,
                    "error": c.error,
                }
                for c in result.checks
            ],
        }
        print(json.dumps(out, indent=2))
        sys.exit(0 if result.all_passed else 1)
    else:
        print("🔍 Velo Zygote Pre-Flight Check")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for i, check in enumerate(result.checks, 1):
            icon = "✅" if check.passed else "❌"
            print(f"[{i}/{len(result.checks)}] {check.name}: {icon}")

            if args.verbose or not check.passed:
                for k, v in check.details.items():
                    print(f"      • {k}: {v}")
                if check.error:
                    print(f"      🚨 Error: {check.error}")
            print("")

        if result.all_passed:
            print("✅ Pre-flight environment checks PASSED")
            sys.exit(0)
        else:
            print("❌ Pre-flight environment checks FAILED")
            sys.exit(1)
