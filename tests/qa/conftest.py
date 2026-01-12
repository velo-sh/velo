"""pytest conftest for Velo QA tests."""
import subprocess
import pytest
import sys
import os
from pathlib import Path
from typing import Any


# Add tests/qa to path for imports
# Add tests/qa to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from conftest_utils import (
    get_timeout_multiplier,
    ci_timeout,
    get_rss,
    get_pss,
    get_ppid,
    get_velo_binary,
    VeloTestEnv,
    T_SHORT,
    T_MEDIUM,
    T_LONG,
    TIMEOUT_MULTIPLIER,
    CI_TIMEOUT,
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
    config.addinivalue_line("markers", "tier0: Smoke tests (<5s) - run always")
    config.addinivalue_line(
        "markers", "tier1: Fast tests (<30s) - security, error handling"
    )
    config.addinivalue_line(
        "markers", "tier2: Standard tests (<10min) - full functionality"
    )
    config.addinivalue_line(
        "markers", "tier3: Heavy tests (~5min) - chaos, stress tests"
    )
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

    config.addinivalue_line(
        "markers", "resource_budget: Resource budget verification tests"
    )


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
        except:
            pass

    yield

    # Clean after module completes
    # RFC-0012: We rely on hermetic isolation (unique TMPDIR/sockets)
    # and the Zygote Guardian thread to prevent leaks.
    # Blind pkill is avoided to support parallel test execution.
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass
    if sock_dir.exists() and sock_dir.name.startswith("velo-"):
        try:
            shutil.rmtree(str(sock_dir))
        except:
            pass


@pytest.fixture(scope="session")
def velo_binary():
    """Pytest fixture: Build and return path to Velo binary."""
    return get_velo_binary()


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
        sys.stderr.write(
            f"\n[Artifacts] Failure detected in {item.name}. Bundling logs...\n"
        )

        try:
            # Locate binary
            root_dir = Path(__file__).parents[2]
            velo_bin = root_dir / "target/debug/velo"
            if not velo_bin.exists():
                velo_bin = root_dir / "target/release/velo"

            if velo_bin.exists():
                log_dir = None

                # Check for isolated env
                if "velo_test_env" in item.funcargs:
                    env = item.funcargs["velo_test_env"]
                    # RFC-0012: Logs are in HOME/.local/state/velo
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
                    safe_name = (
                        item.name.replace("[", "_").replace("]", "_").replace("/", "_")
                    )
                    filename = f"failure-{safe_name}-{ts}.tar.gz"
                    cmd.extend(["--output", filename])

                subprocess.run(cmd, check=False)
        except Exception as e:
            sys.stderr.write(f"[Artifacts] Failed to bundle: {e}\n")
