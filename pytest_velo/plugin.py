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
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Phase 14 P1 Miracle Imports
try:
    from velo_zygote.transport_sync import ZygoteTransport

    from .gateway import ZygoteGateway
except ImportError:
    ZygoteTransport = None  # type: ignore
    ZygoteGateway = None  # type: ignore

# =============================================================================
# Global State
# =============================================================================

_zygote: Any | None = None
_fork_reinit_callbacks: list[Callable[[], None]] = []
_session_socket_path: Path | None = None  # Session-scoped socket for isolation


# =============================================================================
# Session Isolation Helpers (SPEC-0005 INV-SSOT-002: Pool Sovereignty)
# =============================================================================


def _short_hash(s: str) -> str:
    """Generate 6-char hex hash using blake3 (project standard)."""
    import blake3
    return blake3.blake3(s.encode()).hexdigest()[:6]


def _sanitize_name(path: str) -> str:
    """8-char alphanumeric name (Rust parity with paths.rs:142-161)."""
    name = Path(path).name if path else "sess"
    clean = ''.join(c for c in name if c.isalnum() or c == '_')[:8]
    return clean or "sess"


def _session_socket_name(rootdir: str) -> str:
    """Generate unique readable socket name (Rust parity with paths.rs:200).
    
    Format: velo-zygote-{name}-{hash}-v01.sock
    Example: velo-zygote-velo-3f4a2b-v01.sock
    """
    name = _sanitize_name(rootdir)
    # Include PID to ensure uniqueness across parallel sessions
    hash_val = _short_hash(f"{rootdir}:{os.getpid()}")
    return f"velo-zygote-{name}-{hash_val}-v01.sock"


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
    import warnings

    for callback in _fork_reinit_callbacks:
        try:
            callback()
        except Exception as e:
            # DEF-13-003 FIX: Log warning instead of silent pass
            warnings.warn(f"velo_fork_reinit callback failed: {e}", RuntimeWarning, stacklevel=2)


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


def hijack_execnet() -> None:
    """
    Phase 14 P1: Hijack execnet node creation to use Zygote Gateway.
    This eliminates 'double bootstrap' by forking xdist workers directly from Zygote.
    """
    try:
        import execnet.multi

        from .gateway import ZygoteGateway

        # Prevent double hijacking
        if getattr(execnet.multi.Group, "_velo_hijacked", False):
            return

        original_makegateway = execnet.multi.Group.makegateway

        def velo_makegateway(self: Any, spec: Any = None) -> Any:
            import os as _os  # Explicit import to avoid closure scoping issues
            if not spec:
                spec = self.defaultspec
            if not isinstance(spec, execnet.XSpec):
                spec = execnet.XSpec(spec)

            # MIRACLE: Hijack local popen nodes to use Zygote
            if spec.popen:
                # We use the ZygoteGateway which handles the handover
                # It will automatically find the socket and secret via SSOT
                self.allocate_id(spec)
                try:
                    # Capture secret from env (SSOT: VELO_ZYGOTE_AUTH)
                    secret = _os.environ.get("VELO_ZYGOTE_AUTH")
                    gw = ZygoteGateway(spec, secret=secret)
                    self._register(gw)
                    return gw
                except Exception as e:
                    import warnings

                    warnings.warn(f"Zygote Gateway failed: {e}. Falling back to standard popen.", RuntimeWarning)

            return original_makegateway(self, spec)

        execnet.multi.Group.makegateway = velo_makegateway
        execnet.multi.Group._velo_hijacked = True  # type: ignore

        # Also patch the global makegateway for any direct calls
        import execnet

        execnet.makegateway = velo_makegateway

    except ImportError:
        pass  # xdist/execnet not installed


def pytest_configure(config: Any) -> None:
    """Start Zygote server if --velo is enabled."""
    global _zygote

    if config.option.velo:
        # Check xdist compatibility (info log, no longer blocking)
        validate_xdist_compatibility(config)

        # P1-2: Prevent COW thrashing from .pyc writes
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

        # P1 Miracle: Hijack execnet node creation EARLY (before worker spawning)
        # This must happen before xdist creates workers, regardless of velo binary
        if is_xdist_controller():
            hijack_execnet()

        velo_bin = shutil.which("velo")

        # Get preload modules and validate they exist
        preload = getattr(config.option, "velo_preload", "")
        preload_args = []

        if preload:
            # Validate each preload module exists
            for module_name in preload.split(","):
                module_name = module_name.strip()
                if not module_name:
                    continue
                spec = importlib.util.find_spec(module_name)
                if spec is None:
                    raise pytest.UsageError(
                        f"--velo-preload: Module '{module_name}' not found. "
                        f"Ensure the module is installed and accessible."
                    )
            preload_args = ["--preload", preload]

        if velo_bin:
            # Phase 14: Only the controller (or standalone) starts/stops the Zygote
            if is_xdist_controller():
                global _session_socket_path
                
                # Session Isolation: Generate unique socket path for this session
                rootdir = str(config.rootdir)
                socket_name = _session_socket_name(rootdir)
                uid = os.getuid() if hasattr(os, 'getuid') else 0
                import tempfile
                socket_dir = Path(tempfile.gettempdir()) / f"velo-{uid}"
                socket_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                _session_socket_path = socket_dir / socket_name
                # Respect user-provided socket path (allows external Zygote sharing)
                if not os.environ.get("VELO_ZYGOTE_SOCKET"):
                    os.environ["VELO_ZYGOTE_SOCKET"] = str(_session_socket_path)
                
                # SEC-005: Generate forensic secret for this session if not provided
                if not os.environ.get("VELO_ZYGOTE_AUTH"):
                    import uuid

                    os.environ["VELO_ZYGOTE_AUTH"] = str(uuid.uuid4())

                # P1 Miracle: Hijack execnet node creation
                hijack_execnet()
                
                # RAII-style cleanup: register atexit handler
                def _cleanup_zygote() -> None:
                    try:
                        subprocess.run([velo_bin, "zygote", "stop"], capture_output=True, timeout=5)
                        if _session_socket_path and _session_socket_path.exists():
                            _session_socket_path.unlink()
                    except Exception:
                        pass
                atexit.register(_cleanup_zygote)

                try:
                    # Start Zygote in daemon mode with session-specific socket
                    result = subprocess.run(
                        [velo_bin, "zygote", "start", "--daemon"] + preload_args,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        _zygote = {"started_by_pytest": True, "velo_bin": velo_bin}
                    else:
                        import warnings

                        warnings.warn(f"Failed to start Zygote: {result.stderr}", RuntimeWarning)
                        _zygote = True  # Fallback to direct fork mode
                except Exception as e:
                    import warnings

                    warnings.warn(f"Zygote startup error: {e}", RuntimeWarning)
                    _zygote = True  # Fallback
            else:
                # xdist worker: Hot connect to shared Zygote
                _zygote = {"started_by_pytest": False, "velo_bin": velo_bin}
        else:
            # No velo binary, use direct fork mode
            _zygote = True


def pytest_unconfigure(config: Any) -> None:
    """Shutdown Zygote server."""
    global _zygote

    if _zygote:
        # DEF-13-005 FIX: Stop Zygote if we started it
        if isinstance(_zygote, dict) and _zygote.get("started_by_pytest"):
            import subprocess

            velo_bin = _zygote.get("velo_bin")
            if velo_bin:
                try:
                    subprocess.run(
                        [velo_bin, "zygote", "stop"],
                        capture_output=True,
                        timeout=5,
                    )
                except Exception:
                    pass  # Best effort cleanup
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

    # Phase 14: Use real Zygote if available (shared among xdist workers)
    # We use this when we are an xdist worker (started_by_pytest=False)
    if isinstance(_zygote, dict) and "velo_bin" in _zygote:
        velo_bin = _zygote["velo_bin"]
        runner_script = str(Path(__file__).parent / "runner.py")

        try:
            # Pass worker ID if present (common in xdist)
            cmd = [velo_bin, "zygote", "fork", "--script", runner_script, "--arg", item.nodeid]
            worker_id = os.environ.get("PYTEST_XDIST_WorkerId") or os.environ.get("VELO_WORKER_ID")
            if worker_id:
                cmd.extend(["--env", f"VELO_WORKER_ID={worker_id}"])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
            # RFC-0028 Phase 14: Parse JSON result from runner.py
            try:
                # result.stdout may contain noise, but the last line should be our JSON
                lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
                if not lines:
                    return False

                # Try to find the JSON line (usually the last one)
                test_result = None
                for line in reversed(lines):
                    try:
                        test_result = json.loads(line)
                        if isinstance(test_result, dict) and ("passed" in test_result or "error" in test_result):
                            break
                    except json.JSONDecodeError:
                        continue

                if test_result:
                    print(f"DEBUG: Found test result for {item.nodeid}, passed={test_result.get('passed')}")
                    # Re-emit captured test output
                    if test_result.get("stdout"):
                        sys.stdout.write(test_result["stdout"])
                    if test_result.get("stderr"):
                        sys.stderr.write(test_result["stderr"])
                    if test_result.get("error"):
                        sys.stderr.write(f"\nZYGOTE WORKER ERROR: {test_result['error']}\n")

                    return test_result.get("passed", False)
                else:
                    sys.stderr.write(f"\nZYGOTE FORK RAW STDOUT: {result.stdout}\n")
                    sys.stderr.write(f"ZYGOTE FORK RAW STDERR: {result.stderr}\n")

            except Exception as e:
                sys.stderr.write(f"\nFailed to parse Zygote result: {e}\n")
                sys.stderr.write(f"RAW STDOUT: {result.stdout}\n")

            return result.returncode == 0
        except Exception as e:
            import warnings

            warnings.warn(f"Failed to execute test via Zygote: {e}. Falling back to direct fork.", RuntimeWarning)

    # Fallback/Phase 1 Legacy: Direct Fork Mode
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
            # P1-3: Proper pytest integration
            if hasattr(item, "ihook"):
                ihook = item.ihook
                ihook.pytest_runtest_setup(item=item)
                ihook.pytest_runtest_call(item=item)
                ihook.pytest_runtest_teardown(item=item, nextitem=None)
            else:
                # Diagnostic/Mock items in QA tests
                item.runtest()
            exit_code = 0
        except Exception:
            exit_code = 1

        # P0-3 MANDATORY: Use os._exit(), NOT sys.exit()
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

    DEF-13-004 FIX: Properly reports test outcomes to pytest.
    """
    if not getattr(item.config.option, "velo", False) or not _zygote:
        return None  # Fallback to default pytest behavior

    # Phase 14 P1 Miracle Skip: If we are already in a miracle fork, just run locally.
    if os.environ.get("VELO_MIRACLE_WORKER") == "1":
        return None

    from _pytest import timing
    from _pytest.runner import CallInfo

    # Report "setup" phase
    ihook = item.ihook
    ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)

    # Execute in forked child with full P0 compliance
    start = timing.time()
    success = run_in_zygote_fork(item)
    stop = timing.time()

    # DEF-13-004 FIX: Create proper CallInfo to report outcome
    if success:
        # Test passed - create successful CallInfo
        call = CallInfo.from_call(
            lambda: None,  # No-op since already ran
            when="call",
            reraise=None,
        )
    else:
        # Test failed - create failed CallInfo with exception
        def raise_failure() -> None:
            raise AssertionError("Test failed in Zygote fork (exit code != 0)")

        call = CallInfo.from_call(
            raise_failure,
            when="call",
            reraise=None,
        )

    # Override timing from actual fork execution
    call.start = start
    call.stop = stop
    call.duration = stop - start

    # Generate and log the report
    report = ihook.pytest_runtest_makereport(item=item, call=call)
    ihook.pytest_runtest_logreport(report=report)

    # Report teardown (minimal)
    teardown_call = CallInfo.from_call(lambda: None, when="teardown", reraise=None)
    teardown_report = ihook.pytest_runtest_makereport(item=item, call=teardown_call)
    ihook.pytest_runtest_logreport(report=teardown_report)

    ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)

    return True  # We fully handled this test
