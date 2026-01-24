#!/usr/bin/env python3
"""
Velo Constants Sync Script

Generates velo_zygote/constants.py from config/constants.toml (SSOT).

Usage:
    python scripts/sync-constants.py          # Generate constants.py
    python scripts/sync-constants.py --check  # Verify sync (for CI)
"""

import json
import sys
import argparse
import subprocess
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11 fallback

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def get_git_hash() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        hash_val = result.stdout.strip()
        
        # Check for dirty working tree
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if dirty.stdout.strip():
            hash_val += "-dirty"
        return hash_val
    except Exception:
        return "unknown"


def validate_config(config: dict, schema_path: Path) -> bool:
    """Validate config against JSON Schema. Returns True if valid."""
    if not HAS_JSONSCHEMA:
        print("⚠️  jsonschema not installed, skipping validation", file=sys.stderr)
        return True
    
    if not schema_path.exists():
        print(f"⚠️  Schema not found: {schema_path}, skipping validation", file=sys.stderr)
        return True
    
    schema = json.loads(schema_path.read_text())
    
    try:
        jsonschema.validate(config, schema)
        print("✅ Schema validation passed")
        return True
    except jsonschema.ValidationError as e:
        print(f"❌ Schema validation failed: {e.message}", file=sys.stderr)
        print(f"   Path: {' -> '.join(str(p) for p in e.absolute_path)}", file=sys.stderr)
        return False


def generate_constants_py(config: dict, git_hash: str) -> str:
    """Generate Python constants file content."""
    
    py_env = config.get("python_environment", {})
    
    # Format env_vars list
    env_vars_str = ", ".join(f'"{v}"' for v in py_env.get("env_vars", []))
    
    return f'''# Generated from config/constants.toml by scripts/sync-constants.py
# Run 'python scripts/sync-constants.py' after editing config/constants.toml
# DO NOT EDIT MANUALLY

import sys

BUILD_SCM_HASH = "{git_hash}"
PROTOCOL_VERSION = {config["protocol_version"]}
PYTHON_VERSION = "{config["python_version"]}"
SOCKET_PATH_LIMIT = {config["socket_path_limit"]}
MAX_MESSAGE_SIZE = {config["max_message_size"]}
SOCKET_STARTUP_TIMEOUT = {config["socket_startup_timeout"]}
GRACEFUL_SHUTDOWN_TIMEOUT = {config["graceful_shutdown_timeout"]}
DEFAULT_PORT = {config["default_port"]}

# Valid Environment Variables
# VELO_ENV: dev, ci, prod
# VELO_SOCKET_DIR: Override socket directory
# VELO_ZYGOTE_LOG: Override log file path

# Level 0: Global Base (Universal)
SECURITY_BASE_TRUSTED_PREFIXES = "{config["security_base_trusted_prefixes"]}"
SECURITY_BASE_ENV_WHITELIST = "{config["security_base_env_whitelist"]}"
PATH_SOCKET_DIR_NAME = "{config["path_socket_dir_name"]}"
PATH_LOG_DIR_RELATIVE = "{config["path_log_dir_relative"]}"

# Level 1: Platform Defaults (Ensures all constants are importable on ANY platform)
# These are fallback defaults; the platform-specific blocks below override them.
PATH_MACOS_FD_DIR = "{config["path_macos_fd_dir"]}"
PATH_LINUX_FD_DIR = "{config["path_linux_fd_dir"]}"
PATH_MACOS_BASE_SOCKET_PARENT = "{config["path_macos_base_socket_parent"]}"
PATH_LINUX_BASE_SOCKET_PARENT = "{config["path_linux_base_socket_parent"]}"

# Level 1: macOS specific
if sys.platform == "darwin":
    SECURITY_MACOS_BASE_TRUSTED_PREFIXES = "{config["security_macos_base_trusted_prefixes"]}"
    SECURITY_MACOS_BASE_ENV_WHITELIST = "{config["security_macos_base_env_whitelist"]}"
    # Level 2: macOS Environment Overlays
    SECURITY_MACOS_DEV_TRUSTED_PREFIXES = "{config["security_macos_dev_trusted_prefixes"]}"
    SECURITY_MACOS_DEV_ENV_WHITELIST = "{config["security_macos_dev_env_whitelist"]}"
    SECURITY_MACOS_CI_TRUSTED_PREFIXES = "{config["security_macos_ci_trusted_prefixes"]}"
    SECURITY_MACOS_CI_ENV_WHITELIST = "{config["security_macos_ci_env_whitelist"]}"
    SECURITY_MACOS_PROD_TRUSTED_PREFIXES = "{config["security_macos_prod_trusted_prefixes"]}"
    SECURITY_MACOS_PROD_ENV_WHITELIST = "{config["security_macos_prod_env_whitelist"]}"
    # Paths
    PATH_MACOS_BASE_SOCKET_PARENT = "{config["path_macos_base_socket_parent"]}"
    PATH_MACOS_BASE_LOG_PARENT = "{config["path_macos_base_log_parent"]}"
    PATH_MACOS_CI_SOCKET_PARENT = "{config["path_macos_ci_socket_parent"]}"
    PATH_MACOS_FD_DIR = "{config["path_macos_fd_dir"]}"

# Level 1: Linux specific
if sys.platform == "linux":
    SECURITY_LINUX_BASE_TRUSTED_PREFIXES = "{config["security_linux_base_trusted_prefixes"]}"
    SECURITY_LINUX_BASE_ENV_WHITELIST = "{config["security_linux_base_env_whitelist"]}"
    # Level 2: Linux Environment Overlays
    SECURITY_LINUX_DEV_TRUSTED_PREFIXES = "{config["security_linux_dev_trusted_prefixes"]}"
    SECURITY_LINUX_DEV_ENV_WHITELIST = "{config["security_linux_dev_env_whitelist"]}"
    SECURITY_LINUX_CI_TRUSTED_PREFIXES = "{config["security_linux_ci_trusted_prefixes"]}"
    SECURITY_LINUX_CI_ENV_WHITELIST = "{config["security_linux_ci_env_whitelist"]}"
    SECURITY_LINUX_PROD_TRUSTED_PREFIXES = "{config["security_linux_prod_trusted_prefixes"]}"
    SECURITY_LINUX_PROD_ENV_WHITELIST = "{config["security_linux_prod_env_whitelist"]}"
    # Paths
    PATH_LINUX_BASE_SOCKET_PARENT = "{config["path_linux_base_socket_parent"]}"
    PATH_LINUX_BASE_LOG_PARENT = "{config["path_linux_base_log_parent"]}"
    PATH_LINUX_CI_SOCKET_PARENT = "{config["path_linux_ci_socket_parent"]}"
    PATH_LINUX_FD_DIR = "{config["path_linux_fd_dir"]}"

# Security (Phase 10.1)
DEFAULT_BLOCKED_PATHS = [
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library", "/private/etc",
    "/root", "/home",
]

# =============================================================================
# Python Environment SSOT (Phase 7.3+)
# =============================================================================
PYTHON_REQUIRED_VERSION = "{py_env.get("required_version", "3.11")}"
PYTHON_VENV_PATH = "{py_env.get("venv_path", ".venv")}"
PYTHON_LIB_DIR_PATTERN = "{py_env.get("lib_dir_pattern", "lib/python{{version}}")}"
PYTHON_LIB_DYNLOAD_SUBDIR = "{py_env.get("lib_dynload_subdir", "lib-dynload")}"
PYTHON_ENV_VARS = [{env_vars_str}]

# Native Preloading SSOT (Phase 6 Hardening)
_np = {json.dumps(config.get("native_preload", {}))}
NATIVE_PRELOAD_RUNTIME_PREFIX = _np.get("runtime_prefix", "_v_")
NATIVE_PRELOAD_LOCK_ENV = _np.get("lock_env", "VELO_RUNTIME_PRELOAD_LOCK")
NATIVE_PRELOAD_EXE_PATH_ENV = _np.get("exe_path_env", "VELO_RUNTIME_EXE_PATH")
NATIVE_PRELOAD_STRICT_ENV = _np.get("strict_env", "VELO_RUNTIME_STRICT")
NATIVE_PRELOAD_STAGE_PRE_INIT = _np.get("stage_pre_init", "PreInit")
NATIVE_PRELOAD_STAGE_POST_INIT = _np.get("stage_post_init", "PostInit")
'''


def main():
    parser = argparse.ArgumentParser(description="Sync constants from TOML to Python")
    parser.add_argument("--check", action="store_true", help="Check if constants are in sync (for CI)")
    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    toml_path = project_root / "config" / "constants.toml"
    schema_path = project_root / "config" / "constants.schema.json"
    py_path = project_root / "velo_zygote" / "constants.py"
    
    if not toml_path.exists():
        print(f"ERROR: {toml_path} not found", file=sys.stderr)
        sys.exit(1)
    
    # Read TOML
    with open(toml_path, "rb") as f:
        config = tomllib.load(f)
    
    # Validate against schema
    if not validate_config(config, schema_path):
        sys.exit(1)
    
    git_hash = get_git_hash()
    new_content = generate_constants_py(config, git_hash)
    
    if args.check:
        # Check mode: compare with existing file
        if not py_path.exists():
            print(f"ERROR: {py_path} not found. Run 'python scripts/sync-constants.py' to generate.", file=sys.stderr)
            sys.exit(1)
        
        existing = py_path.read_text()
        
        # Compare without BUILD_SCM_HASH (git hash changes frequently)
        def strip_hash(content: str) -> str:
            lines = content.split("\n")
            return "\n".join(line for line in lines if not line.startswith("BUILD_SCM_HASH"))
        
        if strip_hash(existing) != strip_hash(new_content):
            print("ERROR: constants.py is out of sync with config/constants.toml", file=sys.stderr)
            print("Run 'python scripts/sync-constants.py' to regenerate", file=sys.stderr)
            sys.exit(1)
        
        print("✅ constants.py is in sync with config/constants.toml")
        sys.exit(0)
    
    # Generate mode: write file
    py_path.write_text(new_content)
    print(f"✅ Generated {py_path}")


if __name__ == "__main__":
    main()
