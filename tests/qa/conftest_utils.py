import os
import subprocess
import sys
import platform
import pytest
import contextlib
from pathlib import Path
from typing import Any, List, Optional

# =============================================================================
# PLATFORM DETECTION
# =============================================================================

IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

skip_unless_linux = pytest.mark.skipif(
    not IS_LINUX, reason="Test requires Linux"
)

# =============================================================================
# CI TIMEOUT CONFIGURATION
# =============================================================================

def get_timeout_multiplier() -> float:
    if os.environ.get("VELO_TIMEOUT_MULTIPLIER"):
        return float(os.environ["VELO_TIMEOUT_MULTIPLIER"])
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return 6.0
    return 1.0

def ci_timeout(base_seconds: float) -> float:
    return base_seconds * get_timeout_multiplier()

TIMEOUT_MULTIPLIER = get_timeout_multiplier()
CI_TIMEOUT = ci_timeout

# Scaled timeouts
_T_SHORT_BASE = 10
_T_MEDIUM_BASE = 15
_T_LONG_BASE = 60

T_SHORT = _T_SHORT_BASE * TIMEOUT_MULTIPLIER
T_MEDIUM = _T_MEDIUM_BASE * TIMEOUT_MULTIPLIER
T_LONG = _T_LONG_BASE * TIMEOUT_MULTIPLIER

# =============================================================================
# MEMORY & PROCESS HELPERS
# =============================================================================

def get_rss(pid: int) -> int:
    try:
        import psutil
        p = psutil.Process(pid)
        return p.memory_info().rss
    except Exception:
        return 0

def get_pss(pid: int) -> int:
    try:
        import psutil
        p = psutil.Process(pid)
        try:
            return p.memory_full_info().pss
        except AttributeError:
            return p.memory_info().rss
    except Exception:
        return 0

def get_ppid(pid: int) -> int:
    try:
        import psutil
        return psutil.Process(pid).ppid()
    except Exception:
        return 0

def get_process_rss_kb(pid: int) -> int:
    """Get Resident Set Size of a process in KB."""
    if IS_LINUX:
        try:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except (FileNotFoundError, PermissionError):
            pass
    elif IS_MACOS:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    return 0


# =============================================================================
# BINARY RESOLUTION
# =============================================================================

def get_velo_binary() -> str:
    """Find the primary Velo binary (source of truth)."""
    root_dir = Path(__file__).parents[2]
    
    # 1. Environment variable override
    env_binary = os.environ.get("VELO_BINARY")
    if env_binary and Path(env_binary).exists():
        return str(Path(env_binary).resolve())

    # 2. Local build detection (Dev priority)
    candidates = [
        root_dir / "target" / "debug" / "velo",
        root_dir / "target" / "release" / "velo",
    ]

    for path in candidates:
        if path.exists():
            return str(path.resolve())

    # 3. Last resort: auto-build if not in CI
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("🔨 Binary not found. Building...")
        subprocess.run(["cargo", "build"], cwd=root_dir, check=True)
        debug_bin = root_dir / "target" / "debug" / "velo"
        if debug_bin.exists():
            return str(debug_bin.resolve())
            
    raise RuntimeError("Velo binary not found. Run 'cargo build' first.")

# =============================================================================
# HERMETIC ENVIRONMENT (RFC-0012)
# =============================================================================

class VeloTestEnv:
    def __init__(self, root: Path, source_binary: str):
        self.root = root
        self.tmp = root / "tmp"
        self.home = root / "home"
        self.xdg = root / "run"
        self.venv = root / "venv"
        self.bin_dir = root / "bin"

        for d in [self.tmp, self.home, self.xdg, self.bin_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Hermetic Install: Copy the source binary to our isolated environment
        import shutil
        self.velo = str((self.bin_dir / "velo").resolve())
        shutil.copy2(source_binary, self.velo)
        os.chmod(self.velo, 0o755)

        self.env = os.environ.copy()
        current_venv = os.environ.get("VIRTUAL_ENV") or sys.prefix

        self.env.update({
            "TMPDIR": str(self.tmp),
            "HOME": str(self.home),
            "XDG_RUNTIME_DIR": str(self.xdg),
            "VIRTUAL_ENV": current_venv,
            "PATH": f"{current_venv}/bin:{os.environ.get('PATH', '')}",
            "VELO_TEST_MODE": "1",  # Rust config.rs checks this to disable strict_optimizations
            "PYTHONUNBUFFERED": "1",
        })

        # Backward compatibility
        self.path = self.root

    @contextlib.contextmanager
    def env_vars(self, vars: dict):
        """Temporarily update environment variables."""
        old_env = self.env.copy()
        self.env.update(vars)
        try:
            yield self
        finally:
            self.env = old_env

    def run_velo(self, *args, **kwargs) -> subprocess.CompletedProcess:
        env = self.env.copy()
        if "env" in kwargs:
            env.update(kwargs.pop("env"))
        
        # Auto-scale timeout if provided as a number
        timeout = kwargs.pop("timeout", 30)
        if isinstance(timeout, (int, float)):
            timeout = timeout * TIMEOUT_MULTIPLIER

        return subprocess.run(
            [self.velo] + list(args),
            env=env,
            cwd=kwargs.pop("cwd", self.root),
            capture_output=kwargs.pop("capture_output", True),
            text=kwargs.pop("text", True),
            timeout=timeout,
            **kwargs,
        )

    def spawn_velo(self, *args: Any, **kwargs: Any) -> subprocess.Popen:
        env = self.env.copy()
        if "env" in kwargs:
            env.update(kwargs.pop("env"))
        if "text" not in kwargs:
            kwargs["text"] = True
        return subprocess.Popen(
            [self.velo, *args], env=env, cwd=kwargs.pop("cwd", self.root), **kwargs
        )

    def create_app(self, name: str, code: str) -> Path:
        p = self.root / name
        p.write_text(code)
        return p

    def next_port(self) -> int:
        """Get a free port for testing."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]
