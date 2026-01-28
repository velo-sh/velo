# Generated from config/constants.toml by scripts/sync-constants.py
# Run 'python scripts/sync-constants.py' after editing config/constants.toml
# DO NOT EDIT MANUALLY

import sys

BUILD_SCM_HASH = "eabb7e57-dirty"
PROTOCOL_VERSION = 1
PYTHON_VERSION = "3.11"
SOCKET_PATH_LIMIT = 104
MAX_MESSAGE_SIZE = 65536
SOCKET_STARTUP_TIMEOUT = 30
GRACEFUL_SHUTDOWN_TIMEOUT = 60
DEFAULT_PORT = 8000
SANDBOX_NETWORK_ISOLATION = True
SANDBOX_PRIVILEGE_ESCALATION_BLOCK = True

# Valid Environment Variables
# VELO_ENV: dev, ci, prod
# VELO_SOCKET_DIR: Override socket directory
# VELO_ZYGOTE_LOG: Override log file path

# Level 0: Global Base (Universal)
SECURITY_BASE_TRUSTED_PREFIXES = "/usr,/bin,/sbin,/lib,/Library/Frameworks,/Library/Developer/CommandLineTools,${HOME}/.local/share/velo/ci,${HOME}/Library/Python,${HOME}/.local/lib,${HOME}/.local/bin,${HOME}/.local/share/uv/python,${VIRTUAL_ENV}"
SECURITY_BASE_ENV_WHITELIST = "PATH,HOME,USER,LOGNAME,PWD,TMPDIR,PYTHONUNBUFFERED,LANG,LC_ALL,LC_CTYPE,TZ,TERM,MallocNanoZone,VELO_ENV,VELO_TEST_MODE,VELO_ZYGOTE_SOCKET,VELO_ZYGOTE_SOCKET_TIMEOUT,VELO_ZYGOTE_AUTH,VELO_TIMEOUT_MULTIPLIER,VELO_STRICT_NUMA,VELO_ZYGOTE_SHIELD_ACTIVE,VELO_WORKER_DEBUG_LOG,VIRTUAL_ENV,CI,GITHUB_ACTIONS,__CFBundleIdentifier,VELO_IS_ZYGOTE,VELO_WORKER_ID,VELO_NATIVE_PRELOAD_STRICT,VELO_IMPORT_THRESHOLD_MS"
PATH_SOCKET_DIR_NAME = "velo-${UID}"
PATH_LOG_DIR_RELATIVE = ".local/state/velo"

# Level 1: Platform Defaults (Ensures all constants are importable on ANY platform)
# These are fallback defaults; the platform-specific blocks below override them.
PATH_MACOS_FD_DIR = "/dev/fd"
PATH_LINUX_FD_DIR = "/proc/self/fd"
PATH_MACOS_BASE_SOCKET_PARENT = "${HOME}/.local/state/velo/sockets"
PATH_LINUX_BASE_SOCKET_PARENT = "${XDG_RUNTIME_DIR}"

# Level 1: macOS specific
if sys.platform == "darwin":
    SECURITY_MACOS_BASE_TRUSTED_PREFIXES = "${BASE},/opt/homebrew,/opt/local,/usr/local"
    SECURITY_MACOS_BASE_ENV_WHITELIST = "${BASE},__CF_USER_TEXT_ENCODING,XPC_FLAGS,XPC_SERVICE_NAME,TERM_PROGRAM"
    # Level 2: macOS Environment Overlays
    SECURITY_MACOS_DEV_TRUSTED_PREFIXES = "${OS_BASE},${HOME},${VIRTUAL_ENV},${CONDA_PREFIX}"
    SECURITY_MACOS_DEV_ENV_WHITELIST = "${OS_BASE},SHELL,VIRTUAL_ENV,CONDA_PREFIX,PYTHONHOME,DYLD_LIBRARY_PATH,DYLD_FALLBACK_LIBRARY_PATH"
    SECURITY_MACOS_CI_TRUSTED_PREFIXES = "${OS_BASE},/opt/hostedtoolcache,${HOME},${VIRTUAL_ENV}"
    SECURITY_MACOS_CI_ENV_WHITELIST = "${OS_BASE},GITHUB_ACTIONS,GITHUB_WORKSPACE,VIRTUAL_ENV,CONDA_PREFIX,SHELL"
    SECURITY_MACOS_PROD_TRUSTED_PREFIXES = "${OS_BASE}"
    SECURITY_MACOS_PROD_ENV_WHITELIST = "${OS_BASE}"
    # Paths
    PATH_MACOS_BASE_SOCKET_PARENT = "${HOME}/.local/state/velo/sockets"
    PATH_MACOS_BASE_LOG_PARENT = "${HOME}"
    PATH_MACOS_CI_SOCKET_PARENT = "${TMPDIR}"
    PATH_MACOS_FD_DIR = "/dev/fd"

# Level 1: Linux specific
if sys.platform == "linux":
    SECURITY_LINUX_BASE_TRUSTED_PREFIXES = "${BASE},/lib64,/etc/ssl/certs"
    SECURITY_LINUX_BASE_ENV_WHITELIST = "${BASE},XDG_RUNTIME_DIR"
    # Level 2: Linux Environment Overlays
    SECURITY_LINUX_DEV_TRUSTED_PREFIXES = "${OS_BASE},${HOME},${VIRTUAL_ENV},${CONDA_PREFIX}"
    SECURITY_LINUX_DEV_ENV_WHITELIST = "${OS_BASE},SHELL,VIRTUAL_ENV,CONDA_PREFIX,LD_LIBRARY_PATH"
    SECURITY_LINUX_CI_TRUSTED_PREFIXES = "${OS_BASE},/opt/hostedtoolcache,/home/runner,${HOME},${VIRTUAL_ENV}"
    SECURITY_LINUX_CI_ENV_WHITELIST = "${OS_BASE},GITHUB_ACTIONS,GITHUB_WORKSPACE,VIRTUAL_ENV,CONDA_PREFIX,SHELL,LD_LIBRARY_PATH"
    SECURITY_LINUX_PROD_TRUSTED_PREFIXES = "${OS_BASE}"
    SECURITY_LINUX_PROD_ENV_WHITELIST = "${OS_BASE}"
    # Paths
    PATH_LINUX_BASE_SOCKET_PARENT = "${XDG_RUNTIME_DIR}"
    PATH_LINUX_BASE_LOG_PARENT = "${HOME}"
    PATH_LINUX_CI_SOCKET_PARENT = "${XDG_RUNTIME_DIR}"
    PATH_LINUX_FD_DIR = "/proc/self/fd"

# Security (Phase 10.1)
DEFAULT_BLOCKED_PATHS = [
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library", "/private/etc",
    "/root", "/home",
]

# =============================================================================
# Python Environment SSOT (Phase 7.3+)
# =============================================================================
PYTHON_REQUIRED_VERSION = "3.11"
PYTHON_VENV_PATH = ".venv"
PYTHON_LIB_DIR_PATTERN = "lib/python{version}"
PYTHON_LIB_DYNLOAD_SUBDIR = "lib-dynload"
PYTHON_ENV_VARS = ["PYTHONHOME", "VELO_PYTHON_LIB_DIR", "VELO_PYTHON_LIB_DYNLOAD", "VIRTUAL_ENV", "VELO_PYTHON_EXECUTABLE"]

# Native Preloading SSOT (Phase 6 Hardening)
_np = {"runtime_prefix": "_v_", "lock_env": "VELO_RUNTIME_PRELOAD_LOCK", "exe_path_env": "VELO_RUNTIME_EXE_PATH", "strict_env": "VELO_RUNTIME_STRICT", "stage_pre_init": "PreInit", "stage_post_init": "PostInit", "path_integrity": "warn"}
NATIVE_PRELOAD_RUNTIME_PREFIX = _np.get("runtime_prefix", "_v_")
NATIVE_PRELOAD_LOCK_ENV = _np.get("lock_env", "VELO_RUNTIME_PRELOAD_LOCK")
NATIVE_PRELOAD_EXE_PATH_ENV = _np.get("exe_path_env", "VELO_RUNTIME_EXE_PATH")
NATIVE_PRELOAD_STRICT_ENV = _np.get("strict_env", "VELO_RUNTIME_STRICT")
NATIVE_PRELOAD_STAGE_PRE_INIT = _np.get("stage_pre_init", "PreInit")
NATIVE_PRELOAD_STAGE_POST_INIT = _np.get("stage_post_init", "PostInit")
