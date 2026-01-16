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
    """Get Proportional Set Size. Falls back to RSS on macOS."""
    try:
        import psutil
        p = psutil.Process(pid)
        try:
            # PSS is only available on Linux via memory_full_info()
            mem_info = p.memory_full_info()
            return getattr(mem_info, 'pss', mem_info.rss)
        except (AttributeError, psutil.AccessDenied):
            # macOS: fallback to RSS (PSS not available)
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


def get_cow_stats(pid: int) -> dict:
    """Get COW (Copy-on-Write) memory stats for a process.
    
    On Linux: Uses PSS from /proc/[pid]/smaps
    On macOS: Uses vmmap to get DIRTY/RESIDENT ratio
    
    Returns:
        dict with 'resident_kb', 'dirty_kb', 'cow_efficiency' (0-100%)
    """
    result = {"resident_kb": 0, "dirty_kb": 0, "cow_efficiency": 0.0}
    
    if IS_LINUX:
        try:
            pss = 0
            rss = 0
            with open(f"/proc/{pid}/smaps_rollup", "r") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        pss = int(line.split()[1])
                    elif line.startswith("Rss:"):
                        rss = int(line.split()[1])
            result["resident_kb"] = rss
            result["dirty_kb"] = pss  # PSS approximates "private" memory
            if rss > 0:
                result["cow_efficiency"] = (1.0 - pss / rss) * 100
        except (FileNotFoundError, PermissionError):
            pass
    elif IS_MACOS:
        try:
            # Parse vmmap output for TOTAL line
            # Format: TOTAL  VSIZE  RESIDENT  DIRTY  SWAPPED ...
            proc = subprocess.run(
                ["vmmap", "-summary", str(pid)],
                capture_output=True, text=True, timeout=5
            )
            if proc.returncode == 0:
                for line in proc.stdout.split('\n'):
                    if line.startswith("TOTAL"):
                        parts = line.split()
                        # Parse size values (e.g., "87.0M", "1456K")
                        def parse_size(s):
                            s = s.strip()
                            if s.endswith('G'):
                                return int(float(s[:-1]) * 1024 * 1024)
                            elif s.endswith('M'):
                                return int(float(s[:-1]) * 1024)
                            elif s.endswith('K'):
                                return int(float(s[:-1]))
                            return int(s) if s.isdigit() else 0
                        
                        if len(parts) >= 4:
                            result["resident_kb"] = parse_size(parts[2])
                            result["dirty_kb"] = parse_size(parts[3])
                            if result["resident_kb"] > 0:
                                # COW efficiency = (resident - dirty) / resident
                                shared = result["resident_kb"] - result["dirty_kb"]
                                result["cow_efficiency"] = (shared / result["resident_kb"]) * 100
                        break
        except (subprocess.TimeoutExpired, Exception):
            pass
    
    return result


# =============================================================================
# BINARY RESOLUTION
# =============================================================================

def get_velo_binary() -> str:
    """Find the primary Velo binary (source of truth).
    
    Priority order:
    1. VELO_BINARY environment variable (explicit override)
    2. Release binary (preferred for production-like testing)
    3. Debug binary (fallback for development)
    4. Auto-build (only outside CI)
    """
    root_dir = Path(__file__).parents[2]
    
    # 1. Environment variable override (highest priority)
    env_binary = os.environ.get("VELO_BINARY")
    if env_binary and Path(env_binary).exists():
        return str(Path(env_binary).resolve())

    # 2. Local build detection - PREFER RELEASE over debug
    release_bin = root_dir / "target" / "release" / "velo"
    debug_bin = root_dir / "target" / "debug" / "velo"
    
    # Prefer release if it exists and is newer than debug
    if release_bin.exists():
        if debug_bin.exists():
            # Warn if debug is newer (might indicate stale release)
            if debug_bin.stat().st_mtime > release_bin.stat().st_mtime:
                print("⚠️  Warning: debug binary is newer than release. Consider running 'cargo build --release'")
        return str(release_bin.resolve())
    
    if debug_bin.exists():
        print("⚠️  Using debug binary. For accurate testing, use: VELO_BINARY=./target/release/velo")
        return str(debug_bin.resolve())

    # 3. Last resort: auto-build if not in CI
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("🔨 Binary not found. Building release version...")
        subprocess.run(["cargo", "build", "--release"], cwd=root_dir, check=True)
        if release_bin.exists():
            return str(release_bin.resolve())
            
    raise RuntimeError("Velo binary not found. Run 'cargo build --release' first.")

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

        # RFC-0012: First Principles Isolation
        # We must NOT inherit PYTHONHOME from the host, as it overrides VIRTUAL_ENV
        # and causes version mismatches (e.g. Host 3.10 vs Velo 3.11).
        self.env.pop("PYTHONHOME", None)

        # MacOS AF_UNIX 104-char limit hardening (RFC-0019 §10.2)
        if IS_MACOS:
            # If the default tmp dir is too long, redirect VELO_SOCKET_DIR to a shorter /tmp path
            # pytest-generated paths are often very long (/private/var/folders/...)
            default_socket_parent = self.xdg  # Standard XDG_RUNTIME_DIR
            # Rough estimate: parent + "velo-UID" + "v-worker-0-0.sock"
            # 104 - 15 (velo-UID) - 20 (worker-sock) = ~69 chars for parent
            if len(str(default_socket_parent)) > 60:
                short_dir = Path("/tmp") / f"v{os.getpid()}_{id(self) % 1000}"
                short_dir.mkdir(parents=True, exist_ok=True)
                self.env["VELO_SOCKET_DIR"] = str(short_dir)

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
