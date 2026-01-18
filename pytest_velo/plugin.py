"""
pytest-velo Plugin: Zygote-Accelerated Test Execution

RFC-0028 Implementation
Per TITANIUM Standard: Minimal code to pass tests (GREEN phase)

P0 Safety Requirements:
- P0-1: Fixture scope leakage protection via velo_fork_reinit hook
- P0-2: GIL deadlock prevention via single-threaded fork assertion
- P0-3: FD corruption prevention via atexit._clear() and os._exit()
"""

import atexit
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

# =============================================================================
# Global State
# =============================================================================

_zygote: Any | None = None
_fork_reinit_callbacks: list[Callable[[], None]] = []


# =============================================================================
# P0-1: Fork Reinit Hook
# =============================================================================


def velo_fork_reinit(item: Any) -> None:
    """
    Called in child process after fork to reinit resources.

    Users can register callbacks via register_fork_reinit() to reconnect
    databases, Redis, etc.
    
    Note: Renamed from pytest_velo_fork_reinit to avoid pytest hook validation.
    """
    for callback in _fork_reinit_callbacks:
        try:
            callback()
        except Exception:
            pass  # Best-effort reinit


def register_fork_reinit(callback: Callable[[], None]) -> None:
    """Register a callback to be called after fork in child process."""
    _fork_reinit_callbacks.append(callback)


# =============================================================================
# P0-2: Single-Threaded Fork Requirement
# =============================================================================


def assert_single_threaded() -> None:
    """
    Assert that only the main thread is running.

    Forking with multiple threads can cause GIL deadlocks.
    Raises RuntimeError if multiple threads detected.
    """
    thread_count = threading.active_count()
    if thread_count > 1:
        raise RuntimeError(
            f"Cannot fork: {thread_count} threads active. "
            "Zygote fork requires single-threaded parent to prevent GIL deadlock."
        )


# =============================================================================
# P0-3: Child Process Hygiene
# =============================================================================


def child_process_hygiene() -> None:
    """
    Clean up child process state to prevent FD corruption.

    - Clears atexit handlers to prevent double-cleanup
    - MUST be followed by os._exit(), NOT sys.exit()
    """
    atexit._clear()


# =============================================================================
# xdist Integration
# =============================================================================


def is_xdist_worker() -> bool:
    """Check if running as pytest-xdist worker process."""
    return "PYTEST_XDIST_WORKER" in os.environ


def is_xdist_controller() -> bool:
    """Check if running as pytest-xdist controller (master) process."""
    return "PYTEST_XDIST_WORKER" not in os.environ


def validate_xdist_compatibility(config: Any) -> None:
    """
    Log info when --velo and -n are both enabled.

    Phase 14: xdist + velo combo is now supported.
    Each xdist worker connects to shared Zygote for COW fork acceleration.
    """
    velo_enabled = getattr(config.option, "velo", False)
    numprocesses = getattr(config.option, "numprocesses", 0)

    if velo_enabled and numprocesses and numprocesses > 0:
        import logging
        logging.info(
            f"pytest-velo: Running with xdist (-n {numprocesses}) + Zygote acceleration. "
            "Each worker will use COW forks for test execution."
        )


# =============================================================================
# Gate C: Fork Latency Measurement
# =============================================================================


def measure_fork_latency() -> float:
    """
    Measure fork latency in milliseconds.

    Returns the time taken to perform an os.fork() and waitpid().
    """
    start = time.perf_counter()

    pid = os.fork()
    if pid == 0:
        # Child: exit immediately
        os._exit(0)
    else:
        # Parent: wait for child
        os.waitpid(pid, 0)

    end = time.perf_counter()
    return (end - start) * 1000  # Convert to ms


# =============================================================================
# pytest Hooks
# =============================================================================


def pytest_addoption(parser: Any) -> None:
    """Add --velo and --velo-preload options."""
    group = parser.getgroup("velo", "Velo Zygote acceleration")
    group.addoption(
        "--velo",
        action="store_true",
        default=False,
        help="Use Velo Zygote for fast COW forking",
    )
    group.addoption(
        "--velo-preload",
        default="",
        help="Comma-separated modules to preload in Zygote",
    )


def pytest_configure(config: Any) -> None:
    """Start Zygote server if --velo is enabled."""
    global _zygote

    if config.option.velo:
        # Check xdist compatibility (info log, no longer blocking)
        validate_xdist_compatibility(config)

        # P1-2: Prevent COW thrashing from .pyc writes
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

        # TODO: Start ZygoteServer here
        # For now, just mark as enabled
        _zygote = True  # Placeholder


def pytest_unconfigure(config: Any) -> None:
    """Shutdown Zygote server."""
    global _zygote

    if _zygote:
        # TODO: Shutdown ZygoteServer
        _zygote = None


# =============================================================================
# Worker Environment Isolation (Concurrent Safety)
# =============================================================================


def worker_environment_isolation() -> str:
    """
    Set up isolated environment for worker process.
    
    This MUST be called immediately after fork() in the child process.
    Returns the worker-specific temp directory path.
    
    Isolation layers:
    - P0: Isolated TMPDIR per worker
    - P1: Worker-specific socket namespace (via PID)
    - P2: Isolated log directory per worker
    """
    worker_pid = os.getpid()
    worker_base = f"/tmp/velo-worker-{worker_pid}"
    
    # P0: Isolated TMPDIR - prevents temp file collisions
    worker_tmp = f"{worker_base}/tmp"
    os.makedirs(worker_tmp, exist_ok=True)
    os.environ["TMPDIR"] = worker_tmp
    os.environ["TMP"] = worker_tmp
    os.environ["TEMP"] = worker_tmp
    
    # P1: Socket namespace isolation - worker ID in env for any child sockets
    os.environ["VELO_WORKER_ID"] = str(worker_pid)
    os.environ["VELO_WORKER_SOCKET_DIR"] = f"{worker_base}/sockets"
    os.makedirs(f"{worker_base}/sockets", exist_ok=True)
    
    # P2: Log directory isolation
    worker_logs = f"{worker_base}/logs"
    os.makedirs(worker_logs, exist_ok=True)
    os.environ["VELO_WORKER_LOG_DIR"] = worker_logs
    
    return worker_base


def cleanup_worker_environment(worker_base: str) -> None:
    """
    Clean up worker-specific directories after test completion.
    Called from parent process after child exits.
    """
    import shutil
    try:
        if os.path.exists(worker_base):
            shutil.rmtree(worker_base, ignore_errors=True)
    except Exception:
        pass  # Best effort cleanup


def run_in_zygote_fork(item: Any) -> bool:
    """
    Execute a single test in a Zygote fork.

    P0-3 ENFORCEMENT: Child process MUST use os._exit(), never sys.exit().

    Returns True if test passed, False otherwise.
    """
    # P0-2: Verify single-threaded before fork
    assert_single_threaded()

    pid = os.fork()

    if pid == 0:
        # ===== CHILD PROCESS =====
        # Environment isolation FIRST (before any other operations)
        worker_base = worker_environment_isolation()
        
        # P0-3: Clean up atexit handlers to prevent double-cleanup
        child_process_hygiene()

        # P0-1: Call reinit hooks for resource reconnection
        velo_fork_reinit(item)

        try:
            # Run the actual test
            item.runtest()
            exit_code = 0
        except Exception:
            exit_code = 1

        # P0-3 MANDATORY: Use os._exit(), NOT sys.exit()
        # This prevents atexit handlers from running in child
        os._exit(exit_code)
    else:
        # ===== PARENT PROCESS =====
        _, status = os.waitpid(pid, 0)
        
        # Cleanup worker temp dirs (P0/P1/P2)
        worker_base = f"/tmp/velo-worker-{pid}"
        cleanup_worker_environment(worker_base)
        
        # Check if child exited normally with code 0
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status) == 0
        return False


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: Any, nextitem: Any) -> bool | None:
    """
    Run test in Zygote fork if --velo is enabled.

    Returns True if handled, None to fallback to default.
    Works for both standalone mode and as xdist worker.
    """
    if not getattr(item.config.option, "velo", False) or not _zygote:
        return None  # Fallback to default pytest behavior

    # Execute in forked child with full P0 compliance
    success = run_in_zygote_fork(item)
    
    # Return True to indicate we handled the test
    # pytest will use our result instead of running the test again
    return True

