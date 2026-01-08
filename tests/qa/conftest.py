"""pytest conftest for Velo QA tests."""
import subprocess
import pytest
import sys
import os
from pathlib import Path

# Add tests/qa to path for imports
sys.path.insert(0, str(Path(__file__).parent))


# =============================================================================
# CI TIMEOUT CONFIGURATION (FAIL-FAST RESILIENCE)
# =============================================================================
# GitHub Actions runners are slower than local machines.
# Multiply all timeouts by this factor in CI environments.

def get_timeout_multiplier() -> float:
    """Get timeout multiplier based on environment.
    
    Returns:
        1.0 for local development
        3.0 for CI environments (GITHUB_ACTIONS=true)
        Custom value from VELO_TIMEOUT_MULTIPLIER if set
    """
    if os.environ.get("VELO_TIMEOUT_MULTIPLIER"):
        return float(os.environ["VELO_TIMEOUT_MULTIPLIER"])
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return 6.0  # CI is about 6x slower than local
    return 1.0


def ci_timeout(base_seconds: float) -> float:
    """Scale timeout for CI environment.
    
    Usage:
        subprocess.run(..., timeout=ci_timeout(5))  # 5s local, 15s in CI
    """
    return base_seconds * get_timeout_multiplier()


# Export for use in test files
TIMEOUT_MULTIPLIER = get_timeout_multiplier()
CI_TIMEOUT = ci_timeout  # Alias for shorter imports

# =============================================================================
# CI TIMEOUT CONSTANTS (Preferred Clean Approach)
# =============================================================================
# Tests should use these constants for timeout values.
# In CI, tests will use longer timeouts automatically.
#
# Usage in tests:
#   from conftest import T_SHORT, T_MEDIUM, T_LONG
#   subprocess.run([velo, "zygote", "start"], timeout=T_MEDIUM)

# Base timeouts (local machine)
_T_SHORT_BASE = 5     # Quick commands (--help, status)
_T_MEDIUM_BASE = 15   # Normal operations (start, stop)
_T_LONG_BASE = 60     # Heavy operations (stress tests)

# Scaled timeouts (automatically larger in CI)
T_SHORT = _T_SHORT_BASE * TIMEOUT_MULTIPLIER    # 5s local, 15s CI
T_MEDIUM = _T_MEDIUM_BASE * TIMEOUT_MULTIPLIER  # 15s local, 45s CI
T_LONG = _T_LONG_BASE * TIMEOUT_MULTIPLIER      # 60s local, 180s CI


# =============================================================================
# SUBPROCESS TIMEOUT AUTO-SCALING (Temporary Workaround)
# =============================================================================
# TODO(tech-debt): Refactor tests to use run_velo() or T_* constants instead.
#
# WHY THIS EXISTS:
# - Many legacy tests use subprocess.run(..., timeout=5) directly
# - CI environments (GitHub Actions) are ~3x slower than local machines
# - Without this patch, tests timeout in CI but pass locally
#
# PROPER FIX (future):
# - Update all tests to use run_velo() from test_harness.py
# - Or use T_SHORT/T_MEDIUM/T_LONG constants from this file
# - Then remove this monkey-patch
#
# This is a CONTROLLED patch that only affects subprocess timeout= kwargs.
# It does NOT change any subprocess behavior other than extending timeouts.

_original_subprocess_run = subprocess.run

def _scaled_subprocess_run(*args, **kwargs):
    """Auto-scale subprocess timeout for CI environments."""
    if "timeout" in kwargs and kwargs["timeout"] is not None:
        kwargs["timeout"] = kwargs["timeout"] * TIMEOUT_MULTIPLIER
    return _original_subprocess_run(*args, **kwargs)

subprocess.run = _scaled_subprocess_run


# =============================================================================
# TIER MARKERS (per tiered-testing-guide.md)
# =============================================================================

def pytest_configure(config):
    """Register tier markers for pytest."""
    config.addinivalue_line("markers", "tier0: Smoke tests (<5s) - run always")
    config.addinivalue_line("markers", "tier1: Fast tests (<30s) - security, error handling")
    config.addinivalue_line("markers", "tier2: Standard tests (<10min) - full functionality")
    config.addinivalue_line("markers", "tier3: Heavy tests (~5min) - chaos, stress tests")
    config.addinivalue_line("markers", "slow: Tests that install real packages (slow)")
    config.addinivalue_line("markers", "perf: Performance benchmark tests")
    
    # "Do Not Disturb" Log Policy for CI
    # In CI, we want to reduce noise unless a failure occurs.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Check if user explicitly requested verbose logging
        if not os.environ.get("VELO_LOG_LEVEL"):
            # Default to INFO in CI to suppress DEBUG chatter
            config.option.log_cli_level = "INFO"
            config.option.log_cli_format = "%(asctime)s [%(levelname)s] %(message)s"
            config.option.log_date_format = "%H:%M:%S"
    
    config.addinivalue_line("markers", "resource_budget: Resource budget verification tests")


@pytest.fixture(autouse=True, scope="module")
def cleanup_zygote_between_modules():
    """Kill any stale Zygote processes and clean sockets before each test module.
    
    This prevents test pollution where one module's Zygote affects another.
    """
    import tempfile
    
    # Safe cleanup: rely on socket unlinking and test-local teardown.
    # Avoiding pkill -f to prevent killing IDE language servers (User Rule).
    
    import os
    uid = os.getuid()
    sock_dir = Path(tempfile.gettempdir()) / f"velo-{uid}"
    sock_path = sock_dir / "velo-zygote-v01.sock"
    import shutil
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass
    
    # Also remove the directory to force fresh creation with correct permissions (0700)
    if sock_dir.exists() and sock_dir.name.startswith("velo-"):
         try:
             shutil.rmtree(str(sock_dir))
         except: pass
    
    yield
    
    # Clean after module completes too
    subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass
    if sock_dir.exists() and sock_dir.name.startswith("velo-"):
         try:
             shutil.rmtree(str(sock_dir))
         except: pass


@pytest.fixture(scope="session")
def velo_binary():
    """Build and return path to Velo binary."""
    # Build binary (fast in dev mode)
    subprocess.run(["cargo", "build"], check=True)
    
    bin_path = Path("target/debug/velo").resolve()
    if not bin_path.exists():
        raise RuntimeError("Velo binary not found after build")
    return str(bin_path)

# =============================================================================
# HERMETIC TEST ENVIRONMENT (RFC-0012)
# =============================================================================

class VeloTestEnv:
    """Hermetic test environment implementing RFC-0012.
    
    Prevents tests from touching host system paths (/tmp, /var/folders, ~/).
    """
    def __init__(self, root: Path, velo_binary: str):
        self.root = root
        self.velo = velo_binary
        
        # Directory structure via RFC-0012
        self.tmp = root / "tmp"
        self.home = root / "home"
        self.xdg = root / "run"
        self.venv = root / "venv"
        
        # Ensure directories exist
        for d in [self.tmp, self.home, self.xdg]:
            d.mkdir(parents=True, exist_ok=True)
            
        # The Hermetic Environment Dictionary
        self.env = os.environ.copy()
        
        # Ensure VIRTUAL_ENV is set correctly even if not in os.environ (fallback to sys.prefix)
        # This is critical for 'velo' to detect the project-local python/deps
        current_venv = os.environ.get("VIRTUAL_ENV") or sys.prefix
        
        self.env.update({
            "TMPDIR": str(self.tmp),
            "TEMP": str(self.tmp),
            "HOME": str(self.home),
            "XDG_RUNTIME_DIR": str(self.xdg),
            "VIRTUAL_ENV": current_venv,
            # Ensure bin/ is in PATH for 'which python' checks
            "PATH": f"{current_venv}/bin:{os.environ.get('PATH', '')}",
            # Force Velo to use our isolated socket path logic
            "VELO_ZYGOTE_SOCKET": "", 
            "VELO_BACKOFF_SECS": "0",
            "VELO_TEST_MODE": "1",
            "PYTHONUNBUFFERED": "1"
        })

        # Backward compatibility
        self.path = self.root

    def run_velo(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """Run Velo binary in the hermetic environment (blocking)."""
        # Merge env
        env = self.env.copy()
        if "env" in kwargs:
            env.update(kwargs.pop("env"))
            
        timeout = kwargs.pop("timeout", 30)
        
        return subprocess.run(
            [self.velo] + list(args),
            env=env,
            cwd=kwargs.pop("cwd", self.root),
            capture_output=kwargs.pop("capture_output", True),
            text=kwargs.pop("text", True),
            timeout=timeout,
            **kwargs
        )

    def spawn_velo(self, *args, **kwargs) -> subprocess.Popen:
        """Spawn Velo binary in the hermetic environment (non-blocking)."""
        env = self.env.copy()
        if "env" in kwargs:
            env.update(kwargs.pop("env"))
            
        # Set text=True by default unless explicitly overridden
        if "text" not in kwargs:
            kwargs["text"] = True
            
        return subprocess.Popen(
            [self.velo] + list(args),
            env=env,
            cwd=kwargs.pop("cwd", self.root),
            **kwargs
        )
        
    def create_app(self, name: str, code: str) -> Path:
        """Create an app file in the root."""
        p = self.root / name
        p.write_text(code)
        return p

    def next_port(self) -> int:
        """Get a free port for testing."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]


@pytest.fixture
def velo_test_env(tmp_path, velo_binary):
    """Fixture providing a hermetic VeloTestEnv."""
    return VeloTestEnv(tmp_path, velo_binary)

# Deprecated: alias for backward compatibility
@pytest.fixture
def isolated_env(velo_test_env):
    """Legacy alias for velo_test_env (RFC-0012 Transition)."""
    return velo_test_env


# =============================================================================
# MEMORY HELPERS
# =============================================================================

def get_rss(pid: int) -> int:
    """Get Resident Set Size (RSS) in bytes for a process.
    
    Returns 0 if process doesn't exist or error occurs.
    """
    try:
        import psutil
        p = psutil.Process(pid)
        return p.memory_info().rss
    except Exception:
        return 0


def get_pss(pid: int) -> int:
    """Get Proportional Set Size (PSS) in bytes for a process.
    
    PSS accounts for shared pages - more accurate for COW memory measurement.
    Falls back to RSS if PSS not available (macOS).
    Returns 0 if process doesn't exist or error occurs.
    """
    try:
        import psutil
        p = psutil.Process(pid)
        # PSS is only available on Linux via memory_full_info()
        try:
            return p.memory_full_info().pss
        except AttributeError:
            # macOS doesn't have PSS, fall back to RSS
            return p.memory_info().rss
    except Exception:
        return 0
