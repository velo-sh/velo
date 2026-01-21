import contextlib
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# =============================================================================
# PLATFORM DETECTION
# =============================================================================

IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

skip_unless_linux = pytest.mark.skipif(not IS_LINUX, reason="Test requires Linux")

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
            return getattr(mem_info, "pss", mem_info.rss)
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
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except (FileNotFoundError, PermissionError):
            pass
    elif IS_MACOS:
        result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
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
            with open(f"/proc/{pid}/smaps_rollup") as f:
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
            proc = subprocess.run(["vmmap", "-summary", str(pid)], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                for line in proc.stdout.split("\n"):
                    if line.startswith("TOTAL"):
                        parts = line.split()

                        # Parse size values (e.g., "87.0M", "1456K")
                        def parse_size(s):
                            s = s.strip()
                            if s.endswith("G"):
                                return int(float(s[:-1]) * 1024 * 1024)
                            elif s.endswith("M"):
                                return int(float(s[:-1]) * 1024)
                            elif s.endswith("K"):
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


def _validate_binary_platform(binary_path: Path) -> tuple[bool, str]:
    """Validate that a binary is compatible with the current platform.

    Returns:
        (is_valid, reason_if_invalid)
    """
    import platform

    current_system = platform.system().lower()  # 'linux' or 'darwin'

    # Use 'file' command to detect binary architecture on Linux/macOS
    try:
        result = subprocess.run(["file", str(binary_path)], capture_output=True, text=True, timeout=5)
        file_output = result.stdout.lower()

        if current_system == "linux":
            # On Linux, we need ELF binaries
            if "mach-o" in file_output or "macho" in file_output:
                return False, "binary=macos, system=linux"
            if "elf" not in file_output or "linux" not in file_output.replace("linux-gnu", "linux"):
                # Could be a different format - let it try anyway
                pass
        elif current_system == "darwin":
            # On macOS, we need Mach-O binaries
            if "elf" in file_output:
                return False, "binary=linux, system=macos"

        return True, ""
    except Exception:
        # If 'file' command fails, assume it's OK (don't block tests)
        return True, ""


def get_velo_binary() -> str:
    """Find the primary Velo binary (source of truth).

    Priority order:
    1. VELO_BINARY environment variable (explicit override)
    2. Path sensing relative to this file
    3. Path sensing relative to current working directory
    4. Auto-build (only outside CI)

    All candidates are validated for platform compatibility before returning.
    """
    import pytest

    # 1. Environment variable override (highest priority)
    env_binary = os.environ.get("VELO_BINARY")
    if env_binary and Path(env_binary).exists():
        bin_path = Path(env_binary).resolve()
        valid, reason = _validate_binary_platform(bin_path)
        if not valid:
            pytest.skip(f"Binary platform mismatch: {reason}. Rebuild with 'cargo build --release'")
        return str(bin_path)

    # 2. Strategy: Try to find repo root
    # A: Relative to this file (tests/qa/conftest_utils.py)
    root_file = Path(__file__).resolve().parents[2]
    # B: Relative to CWD
    root_cwd = Path.cwd().resolve()

    # Check candidates for repo root (must contain a 'target' or 'src' as a sanity check)
    candidates = [root_file, root_cwd]

    # Also check if we are already in the repo root or a subdirectory
    curr = root_cwd
    for _ in range(5):
        if (curr / "Cargo.toml").exists():
            candidates.append(curr)
            break
        if curr.parent == curr:
            break
        curr = curr.parent

    for root in candidates:
        release_bin = root / "target" / "release" / "velo"
        debug_bin = root / "target" / "debug" / "velo"

        for bin_path in [release_bin, debug_bin]:
            if bin_path.exists():
                valid, reason = _validate_binary_platform(bin_path)
                if not valid:
                    # Skip this binary, try next candidate
                    print(f"⚠️  Skipping {bin_path}: platform mismatch ({reason})")
                    continue
                if bin_path == debug_bin:
                    print(f"⚠️  Using debug binary found at {debug_bin}")
                return str(bin_path.resolve())

    # 3. Last resort: auto-build if not in CI
    if os.environ.get("GITHUB_ACTIONS") != "true" and (root_cwd / "Cargo.toml").exists():
        print("🔨 Binary not found. Building release version...")
        try:
            subprocess.run(["cargo", "build", "--release"], cwd=root_cwd, check=True)
            release_bin = root_cwd / "target" / "release" / "velo"
            if release_bin.exists():
                valid, reason = _validate_binary_platform(release_bin)
                if valid:
                    return str(release_bin.resolve())
        except Exception as e:
            print(f"❌ Failed to auto-build: {e}")

    raise RuntimeError(
        "Velo binary not found or platform mismatch. Run 'cargo build --release' first or set VELO_BINARY."
    )


def get_repo_root() -> Path:
    """Find the repository root consistently across host and container.

    Priority:
    1. Parent of VELO_BINARY if set
    2. Path sensing relative to this file
    3. Path sensing relative to current working directory (upward search)
    """
    env_binary = os.environ.get("VELO_BINARY")
    if env_binary:
        bin_path = Path(env_binary).resolve()
        # bin is in root/target/[release|debug]/velo
        return bin_path.parents[2]

    # Try sensing relative to file
    root_file = Path(__file__).resolve().parents[2]
    if (root_file / "Cargo.toml").exists():
        return root_file

    # Try sensing relative to CWD (upward search)
    curr = Path.cwd().resolve()
    for _ in range(5):
        if (curr / "Cargo.toml").exists():
            return curr
        if curr.parent == curr:
            break
        curr = curr.parent

    # Default to CWD if all else fails (might be in container root)
    return Path.cwd().resolve()


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

        self.env.update(
            {
                "TMPDIR": str(self.tmp),
                "HOME": str(self.home),
                "XDG_RUNTIME_DIR": str(self.xdg),
                "VIRTUAL_ENV": current_venv,
                "PATH": f"{current_venv}/bin:{os.environ.get('PATH', '')}",
                "VELO_TEST_MODE": "1",  # Rust config.rs checks this to disable strict_optimizations
                "PYTHONUNBUFFERED": "1",
            }
        )

        # RFC-0012: First Principles Isolation
        # We must NOT inherit PYTHONHOME from the host, as it overrides VIRTUAL_ENV
        # and causes version mismatches (e.g. Host 3.10 vs Velo 3.11).
        if "PYTHONHOME" in self.env:
            sys.stderr.write(
                f"\n⚠️  [VeloTestEnv] Sanitizing Host Environment: Removed conflicting PYTHONHOME='{self.env['PYTHONHOME']}' to enforce hermetic Velo runtime.\n"
            )
            self.env.pop("PYTHONHOME")

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
        return subprocess.Popen([self.velo, *args], env=env, cwd=kwargs.pop("cwd", self.root), **kwargs)

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
