import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

# Add tests/qa to path for imports
# Add tests/qa to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from conftest_utils import (
    TIMEOUT_MULTIPLIER,
    VeloTestEnv,
    get_velo_binary,
)

# =============================================================================
# MIDDLEWARE HELPERS
# =============================================================================

UDS_PROXY_MIDDLEWARE_CODE = """
class UDSProxyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope.get("client") is None:
            headers = dict(scope.get("headers", []))
            try:
                # Try to restore client from X-Forwarded-For
                forwarded = headers.get(b"x-forwarded-for")
                if forwarded:
                    # simple parse: take the first IP
                    ip = forwarded.decode("latin1").split(",")[0].strip()
                    # mock port 0 as we don't know the real source port
                    scope["client"] = (ip, 0)
            except (UnicodeDecodeError, AttributeError, IndexError, ValueError):
                pass
        await self.app(scope, receive, send)
"""

# =============================================================================
# SUBPROCESS TIMEOUT AUTO-SCALING (Temporary Workaround)
# =============================================================================

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
    config.addinivalue_line("markers", "tier0: Smoke tests (<10s) - run always")
    config.addinivalue_line("markers", "tier1: Fast tests (<60s) - security, core logic")
    config.addinivalue_line("markers", "tier2: Standard tests (<10min) - full functional integration")
    config.addinivalue_line("markers", "tier3: Heavy tests (>10min) - stress, resource leakage")
    config.addinivalue_line("markers", "tier4: Chaos/Flood tests - extreme scenarios")
    config.addinivalue_line("markers", "slow: Tests that install real packages (slow)")
    config.addinivalue_line("markers", "perf: Performance benchmark tests")
    config.addinivalue_line("markers", "chaos: Extreme scenarios and process destruction")
    config.addinivalue_line("markers", "flood: High-concurrency / IPC flooding tests")

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


# =============================================================================
# SESSION-SCOPED LOG DIRECTORY (P1 Fix: Artifact Bundling Scope)
# =============================================================================

# Global to store session log dir path for use in pytest_runtest_makereport
_session_log_dir: Path | None = None


@pytest.fixture(scope="session", autouse=True)
def session_log_directory(tmp_path_factory):
    """
    Create a unique log directory for this pytest session.

    This ensures artifact bundling only collects current session logs,
    not the accumulated 26GB+ of historical logs.
    """
    global _session_log_dir

    # Create session-specific log dir
    session_id = f"session-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    session_dir = Path.home() / ".local/state/velo" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Export for child processes (Zygote, workers, etc.)
    os.environ["VELO_SESSION_LOG_DIR"] = str(session_dir)

    # Store globally for artifact collection
    _session_log_dir = session_dir

    sys.stderr.write(f"[Session] Log dir: {session_dir}\n")

    yield session_dir

    # Optional: Cleanup on success (keep on failure for debugging)
    # import shutil
    # shutil.rmtree(session_dir, ignore_errors=True)


@pytest.fixture(autouse=True, scope="module")
def cleanup_zygote_between_modules():
    """Kill any stale Zygote processes and clean sockets before each test module.

    This prevents test pollution where one module's Zygote affects another.
    """
    import shutil
    import tempfile

    uid = os.getuid()

    # All possible socket locations
    socket_paths = [
        # Legacy temp-based path
        Path(tempfile.gettempdir()) / f"velo-{uid}" / "velo-zygote-v01.sock",
        # XDG state path
        Path.home() / ".local" / "state" / "velo" / "zygote.sock",
        # Direct zygote socket
        Path.home() / ".local" / "state" / "velo" / "velo-zygote-v01.sock",
    ]

    def cleanup_sockets():
        for sock_path in socket_paths:
            if sock_path.exists():
                try:
                    sock_path.unlink()
                except OSError:
                    pass
            # Also clean parent directory if it's a velo socket dir
            parent = sock_path.parent
            if parent.exists() and parent.name in ("velo", f"velo-{uid}"):
                # Only remove socket file, not the entire dir
                pass

        # Clean temp-based socket dir completely
        sock_dir = Path(tempfile.gettempdir()) / f"velo-{uid}"
        if sock_dir.exists() and sock_dir.name.startswith("velo-"):
            try:
                shutil.rmtree(str(sock_dir))
            except OSError:
                pass

    cleanup_sockets()
    yield
    cleanup_sockets()


@pytest.fixture(scope="session")
def velo_binary():
    """Pytest fixture: Build and return path to Velo binary with arch check."""
    import platform

    binary_path = get_velo_binary()

    # Pure-Python binary format detection (no 'file' command needed)
    def detect_binary_platform(path: str) -> str:
        """Detect if binary is ELF (Linux) or Mach-O (macOS) using magic numbers."""
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
                # ELF magic: 0x7F 'E' 'L' 'F'
                if magic == b"\x7fELF":
                    return "linux"
                # Mach-O magic: 0xFEEDFACE (32-bit), 0xFEEDFACF (64-bit)
                # or fat binary: 0xCAFEBABE
                if magic[:4] in (
                    b"\xfe\xed\xfa\xce",
                    b"\xfe\xed\xfa\xcf",
                    b"\xcf\xfa\xed\xfe",
                    b"\xce\xfa\xed\xfe",
                    b"\xca\xfe\xba\xbe",
                    b"\xbe\xba\xfe\xca",
                ):
                    return "macos"
        except Exception:
            pass
        return "unknown"

    binary_platform = detect_binary_platform(binary_path)
    current_platform = "linux" if platform.system() == "Linux" else "macos"

    # Check for platform mismatch
    if binary_platform != "unknown" and binary_platform != current_platform:
        pytest.skip(
            f"Binary platform mismatch: binary={binary_platform}, system={current_platform}. "
            f"Rebuild with 'cargo build --release'"
        )

    return binary_path


@pytest.fixture
def velo_test_env(tmp_path, velo_binary):
    """Fixture providing a hermetic VeloTestEnv."""
    return VeloTestEnv(tmp_path, velo_binary)


@pytest.fixture
def isolated_env(velo_test_env):
    """Legacy alias for velo_test_env (RFC-0012 Transition)."""
    return velo_test_env


# =============================================================================
# FAILURE ARTIFACT COLLECTION (Phase 4)
# =============================================================================


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture logs and state on test failure."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        # Skip bundling for simple assertion failures or import errors
        # to ensure fast failure feedback
        if "ImportError" in str(report.longrepr) or "ModuleNotFoundError" in str(report.longrepr):
            return

        # Skip bundling if env var is set (avoids 26GB state dir hang)
        if os.environ.get("VELO_SKIP_FAILURE_BUNDLE") == "1":
            sys.stderr.write(f"\n[Artifacts] Skipping bundle for {item.name} (VELO_SKIP_FAILURE_BUNDLE=1)\n")
            return

        sys.stderr.write(f"\n[Artifacts] Failure detected in {item.name}. Bundling logs...\n")

        try:
            # Locate binary
            root_dir = Path(__file__).parents[2]
            velo_bin = root_dir / "target/debug/velo"
            if not velo_bin.exists():
                velo_bin = root_dir / "target/release/velo"

            if velo_bin.exists():
                log_dir = None

                # Priority 1: Use session-scoped log directory (P1 fix)
                if _session_log_dir and _session_log_dir.exists():
                    log_dir = _session_log_dir
                    sys.stderr.write(f"📦 Collecting failure bundle from: {log_dir}\n")
                # Priority 2: Check for isolated test env
                elif "velo_test_env" in item.funcargs:
                    env = item.funcargs["velo_test_env"]
                    log_path = env.home / ".local/state/velo"
                    if log_path.exists():
                        log_dir = log_path
                elif "isolated_env" in item.funcargs:
                    env = item.funcargs["isolated_env"]
                    log_path = env.home / ".local/state/velo"
                    if log_path.exists():
                        log_dir = log_path

                cmd = [str(velo_bin), "bundle", "collect"]
                if log_dir:
                    cmd.extend(["--log-dir", str(log_dir)])
                    # Unique filename
                    import time

                    ts = int(time.time())
                    safe_name = item.name.replace("[", "_").replace("]", "_").replace("/", "_")
                    filename = f"failure-{safe_name}-{ts}.tar.gz"
                    cmd.extend(["--output", filename])

                # Add timeout to prevent hanging (fail fast principle)
                subprocess.run(cmd, check=False, timeout=5)
        except subprocess.TimeoutExpired:
            sys.stderr.write("[Artifacts] Bundle collection timed out (5s limit)\n")
        except Exception as e:
            sys.stderr.write(f"[Artifacts] Failed to bundle: {e}\n")
