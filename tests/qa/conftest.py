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
        return 3.0  # CI is about 3x slower than local
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
# AUTOMATIC SUBPROCESS TIMEOUT SCALING
# =============================================================================
# Monkey-patch subprocess.run to automatically scale timeouts in CI.
# This ensures ALL tests get scaled timeouts without code changes.

_original_subprocess_run = subprocess.run

def _patched_subprocess_run(*args, **kwargs):
    """Wrapper that scales timeout by VELO_TIMEOUT_MULTIPLIER."""
    if "timeout" in kwargs and kwargs["timeout"] is not None:
        original_timeout = kwargs["timeout"]
        kwargs["timeout"] = original_timeout * TIMEOUT_MULTIPLIER
    return _original_subprocess_run(*args, **kwargs)

# Apply the patch globally
subprocess.run = _patched_subprocess_run

# Also patch Popen.wait and Popen.communicate for good measure
_original_popen_wait = subprocess.Popen.wait
_original_popen_communicate = subprocess.Popen.communicate

def _patched_popen_wait(self, timeout=None):
    """Wrapper that scales timeout."""
    if timeout is not None:
        timeout = timeout * TIMEOUT_MULTIPLIER
    return _original_popen_wait(self, timeout=timeout)

def _patched_popen_communicate(self, input=None, timeout=None):
    """Wrapper that scales timeout."""
    if timeout is not None:
        timeout = timeout * TIMEOUT_MULTIPLIER
    return _original_popen_communicate(self, input=input, timeout=timeout)

subprocess.Popen.wait = _patched_popen_wait
subprocess.Popen.communicate = _patched_popen_communicate




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
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass
    
    yield
    
    # Clean after module completes too
    subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass


# =============================================================================
# UNIFIED TEST ENVIRONMENT
# =============================================================================
# Use this fixture to ensure consistent test environments between local and CI.
# Every test using this fixture gets a fresh, isolated venv with NO extra deps.

@pytest.fixture
def isolated_env(tmp_path):
    """Create an isolated test environment with clean venv.
    
    This fixture ensures:
    - Fresh venv with NO extra dependencies (no uvicorn, no fastapi)
    - Same behavior on local machine and CI
    - Proper cleanup after test
    
    Usage:
        def test_something(isolated_env):
            env = isolated_env
            # env.path - temp directory
            # env.python - path to python in isolated venv
            # env.velo - path to velo binary
            # env.install("package") - install package in isolated venv
            # env.create_app("main.py", code) - create app file
    """
    import shutil
    
    class IsolatedEnv:
        def __init__(self, path: Path):
            self.path = path
            self.venv_path = path / ".venv"
            self.python = self.venv_path / "bin" / "python"
            
            # Find velo binary
            repo_root = Path(__file__).parent.parent.parent
            release = repo_root / "target" / "release" / "velo"
            debug = repo_root / "target" / "debug" / "velo"
            self.velo = str(release) if release.exists() else str(debug)
            
        def setup(self):
            """Create isolated venv."""
            subprocess.run(
                ["uv", "venv", "--seed", str(self.venv_path)],
                cwd=self.path, check=True, capture_output=True
            )
            # Install blake3 for hash verification and uvicorn for server testing
            subprocess.run(
                ["uv", "pip", "install", "-q", "--python", str(self.python), "blake3", "uvicorn", "fastapi"],
                cwd=self.path, capture_output=True
            )
            # Create empty uv.lock so velo detects it as a project
            (self.path / "uv.lock").write_text("{}")
            return self

            
        def install(self, *packages):
            """Install packages in isolated venv."""
            subprocess.run(
                ["uv", "pip", "install", "-q", "--python", str(self.python)] + list(packages),
                cwd=self.path, capture_output=True
            )
            
        def create_app(self, name: str, code: str):
            """Create app file."""
            (self.path / name).write_text(code)
            
        def run_velo(self, *args, **kwargs) -> subprocess.CompletedProcess:
            """Run velo command in isolated environment."""
            timeout = kwargs.pop("timeout", 30)
            return subprocess.run(
                [self.velo] + list(args),
                cwd=self.path,
                capture_output=True,
                text=True,
                timeout=timeout,
                **kwargs
            )
    
    env = IsolatedEnv(tmp_path).setup()
    yield env
    
    # Cleanup
    try:
        shutil.rmtree(tmp_path)
    except:
        pass


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

