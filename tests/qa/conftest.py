"""pytest conftest for Velo QA tests."""
import subprocess
import pytest
import sys
from pathlib import Path

# Add tests/qa to path for imports
sys.path.insert(0, str(Path(__file__).parent))


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
    
    # Clean before module runs
    subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)
    
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
                ["uv", "pip", "install", "-q", "--python", str(self.python), "blake3", "uvicorn"],
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

