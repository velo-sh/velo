"""
pytest-velo Plugin: Zygote-Accelerated Test Execution

RFC-0028 Implementation
Per TITANIUM Standard: Minimal code to pass tests (GREEN phase)

P0 Safety Requirements:
- P0-1: Fixture scope leakage protection via pytest_velo_fork_reinit hook
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


def pytest_velo_fork_reinit(item: Any) -> None:
    """
    Hook called in child process after fork to reinit resources.

    Users can register callbacks via register_fork_reinit() to reconnect
    databases, Redis, etc.
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
# Gate B: xdist Mutual Exclusivity
# =============================================================================


def validate_xdist_exclusivity(config: Any) -> None:
    """
    Validate that --velo and -n are not both enabled.

    Raises pytest.UsageError if both are enabled.
    """
    velo_enabled = getattr(config.option, "velo", False)
    numprocesses = getattr(config.option, "numprocesses", 0)

    if velo_enabled and numprocesses and numprocesses > 0:
        raise pytest.UsageError(
            "--velo and -n (pytest-xdist) are mutually exclusive. "
            "Use --velo for Zygote acceleration OR -n for xdist parallelism."
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
        # Validate xdist exclusivity
        validate_xdist_exclusivity(config)

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
        # P0-3: Clean up atexit handlers to prevent double-cleanup
        child_process_hygiene()

        # P0-1: Call reinit hooks for resource reconnection
        pytest_velo_fork_reinit(item)

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
        # Check if child exited normally with code 0
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status) == 0
        return False


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: Any, nextitem: Any) -> bool | None:
    """
    Run test in Zygote fork if --velo is enabled.

    Returns True if handled, None to fallback to default.
    """
    if not getattr(item.config.option, "velo", False) or not _zygote:
        return None  # Fallback to default pytest behavior

    # Execute in forked child with full P0 compliance
    # TODO: When Zygote integration is complete, use Zygote fork
    # For now, use direct fork for testing
    # success = run_in_zygote_fork(item)
    # return success

    # Fallback for now until Zygote server is wired
    return None
