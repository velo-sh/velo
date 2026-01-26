"""
Velo Lifecycle Management
"""

import os
import random
import signal
import sys
import threading
import time
from collections import deque
from enum import Enum, auto
from typing import Any


class IdlePool:
    """
    P0: Pre-forked Idle Pool (RFC-0028 Phase 14).
    Maintains a pool of pre-forked processes to reduce on-path latency.
    Includes Adaptive Scaling to handle burst demands.
    """

    def __init__(self, size: int = 4):
        self._target_size = size
        self._min_size = 2
        self._max_size = 32
        self.pool: deque[tuple[int, int]] = deque()  # (pid, control_pipe_fd)
        self.lock = threading.Lock()

    def add(self, pid: int, pipe_fd: int) -> None:
        with self.lock:
            if len(self.pool) < self._max_size:
                self.pool.append((pid, pipe_fd))
            else:
                LogUtils.log(f"IdlePool Overflow: Terminating extra worker {pid}")
                os.close(pipe_fd)
                os.kill(pid, signal.SIGKILL)

    def pop(self) -> tuple[int, int] | None:
        with self.lock:
            if self.pool:
                worker = self.pool.popleft()
                # Adaptive logic: If we are low, boost target size
                if len(self.pool) < self._min_size:
                    self._target_size = min(self._max_size, self._target_size + 2)
                return worker
            else:
                # Burst detected! Maximize target size immediately
                self._target_size = min(self._max_size, self._target_size + 4)
                return None

    def get_count(self) -> int:
        return len(self.pool)

    def maintenance(self) -> None:
        """Decay target size if idle for a while (called by Zygote loop)."""
        with self.lock:
            if self.get_count() == self._target_size and self._target_size > self._min_size:
                # Slow decay
                self._target_size = max(self._min_size, self._target_size - 1)

    def get_metrics(self) -> dict[str, Any]:
        """Return OpenMetrics-compliant metrics for Prometheus.

        Metrics follow naming convention: velo_zygote_<subsystem>_<name>
        """
        with self.lock:
            current = len(self.pool)
            target = self._target_size
            return {
                "velo_zygote_pool_idle_count": current,
                "velo_zygote_pool_target_size": target,
                "velo_zygote_pool_min_size": self._min_size,
                "velo_zygote_pool_max_size": self._max_size,
                "velo_zygote_pool_utilization_ratio": current / target if target > 0 else 0.0,
            }


class ZygoteState(Enum):
    """
    Formalized Zygote Service States.
    RFC-0012: SSOT for protocol state machine.
    """

    INIT = auto()  # Bootstrapping environment
    IDLE = auto()  # Ready to accept connections
    PRELOADING = auto()  # Currently loading modules
    READY = auto()  # Warm and ready for high-speed fork
    SHUTDOWN = auto()  # Graceful exit initiated
    ERROR = auto()  # Critical failure state


class StateTransitionError(Exception):
    """Raised when an invalid Zygote state transition is attempted."""

    pass


try:
    from .utils import LogUtils
except (ImportError, ValueError):
    from utils import LogUtils  # type: ignore[no-redef, import-not-found]


class WorkerRegistry:
    """Layer 3: State Management - Tracks worker lifecycle.

    Thread-safe implementation using RLock for read-heavy workloads.
    RLock allows reentrant locking (is_alive can call remove safely).
    """

    def __init__(self, worker_ttl: int = 3600):
        self.workers: dict[int, tuple[float, Any]] = {}  # pid -> (start_time, metadata)
        self.worker_ttl = worker_ttl
        self._lock = threading.RLock()  # Reentrant lock for nested calls

    def add(self, pid: int, metadata: Any = None) -> None:
        with self._lock:
            self.workers[pid] = (time.time(), metadata)

    def remove(self, pid: int) -> None:
        with self._lock:
            self.workers.pop(pid, None)

    def is_alive(self, pid: int) -> bool:
        with self._lock:
            if pid not in self.workers:
                return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            self.remove(pid)  # RLock allows reentrant call
            return False

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {"worker_count": len(self.workers), "pids": list(self.workers.keys())}

    def get_metrics(self) -> dict[str, Any]:
        """Return OpenMetrics-compliant metrics for Prometheus.

        Metrics follow naming convention: velo_zygote_<subsystem>_<name>
        """
        now = time.time()
        with self._lock:
            count = len(self.workers)
            oldest_age = 0.0
            if self.workers:
                oldest_start = min(start for start, _ in self.workers.values())
                oldest_age = now - oldest_start
            return {
                "velo_zygote_workers_active_count": count,
                "velo_zygote_workers_ttl_seconds": self.worker_ttl,
                "velo_zygote_workers_oldest_age_seconds": round(oldest_age, 2),
            }

    def start_guardian(self, parent_pid: int, ttl: int, monitor_parent: bool = True) -> None:
        """Guardian thread to prevent orphans."""

        def guardian() -> None:
            while True:
                time.sleep(1)
                # 1. Check parent
                if monitor_parent:
                    try:
                        os.kill(parent_pid, 0)
                    except ProcessLookupError:
                        LogUtils.log("Parent process died. Zygote cleaning up workers and exiting.")
                        # RFC-0012 C.6: Kill all workers before Zygote exits
                        self.kill_all()
                        os._exit(0)

                # Check for kill signal file or other termination conditions if needed

        t = threading.Thread(target=guardian, daemon=True)
        t.start()

    def kill_all(self) -> None:
        """Emergency cleanup of all workers."""
        with self._lock:
            pids = list(self.workers.keys())
        sys.stderr.write(f"\n[ZYGOTE] Eradicating {len(pids)} workers: {pids}\n")
        sys.stderr.flush()
        # RFC-0012 C.6: Robust Eradication - Kill all registered workers
        # Transitioning to SIGTERM to allow for graceful shutdown and signal proxying verification.
        for pid in pids:
            try:
                sys.stderr.write(f"[ZYGOTE] SIGTERM -> PID {pid}\n")
                sys.stderr.flush()
                # Use SIGTERM to allow graceful cleanup (required for test_signal_proxying)
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

        # Give workers a moment to process SIGTERM before Zygote itself exits
        time.sleep(0.1)
        with self._lock:
            self.workers.clear()
        sys.stderr.write("[ZYGOTE] Worker eradication complete.\n")
        sys.stderr.flush()

    def reap_stale(self) -> None:
        """Cleanup logic for timed-out or missing workers."""
        now = time.time()
        with self._lock:
            stale_pids = [pid for pid, (start_time, _) in self.workers.items() if now - start_time > self.worker_ttl]
        for pid in stale_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
            self.remove(pid)


class ReinitHooks:
    """
    Layer 3: Hook-based Re-initialization system.

    SPEC-0005 Compliance: Singleton pattern with encapsulated hook methods.
    All post-fork re-initialization logic is centralized here.
    """

    _instance: "ReinitHooks | None" = None

    def __init__(self) -> None:
        self.hooks: list[Any] = []

    @classmethod
    def get_instance(cls) -> "ReinitHooks":
        """Get the singleton ReinitHooks registry."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_default_hooks()
        return cls._instance

    def register(self, hook_func: Any) -> None:
        """Register a hook to run after fork."""
        self.hooks.append(hook_func)

    def run_all(self, *args: Any, **kwargs: Any) -> None:
        """Execute all registered hooks."""
        for hook in self.hooks:
            try:
                hook(*args, **kwargs)
            except Exception as e:
                LogUtils.log(f"Hook Failure: {hook.__name__}: {e}")

    def _register_default_hooks(self) -> None:
        """Register the standard post-fork hooks."""
        self.register(self.hook_security)
        self.register(self.hook_computing)
        self.register(self.hook_telemetry)
        self.register(self.hook_isolation)

    @staticmethod
    def hook_security(keep_fds: set[int] | None = None, **kwargs: Any) -> None:
        """Industrial Grade Cord-Cutting."""
        # 1. Close all non-standard file descriptors
        try:
            from .constants import PATH_LINUX_FD_DIR, PATH_MACOS_FD_DIR
        except (ImportError, ValueError):
            from constants import PATH_LINUX_FD_DIR, PATH_MACOS_FD_DIR  # type: ignore[no-redef, import-not-found]

        fd_dir = PATH_MACOS_FD_DIR if sys.platform == "darwin" else PATH_LINUX_FD_DIR
        try:
            fds = os.listdir(fd_dir)
            for fd_str in fds:
                try:
                    fd = int(fd_str)
                    if fd > 2 and (keep_fds is None or fd not in keep_fds):
                        # SEC-P0-001: Close FDs from parent Zygote
                        os.close(fd)
                except (ValueError, OSError):
                    continue
        except OSError as e:
            LogUtils.log(
                f"Forensic Cleanup Warning: Failed to list descriptors in '{fd_dir}': {e}. Falling back to range scan."
            )
            # Fallback for systems without /proc or /dev/fd
            for fd in range(3, 1024):
                if keep_fds is None or fd not in keep_fds:
                    try:
                        os.close(fd)
                    except Exception:
                        pass

        # 2. Reset signal handlers
        for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGCHLD]:
            try:
                signal.signal(sig, signal.SIG_DFL)
            except Exception:
                pass

        # 2.5 Asyncio Event Loop Cleanup (DEF-VTEST-ASYNCIO)
        # Forked workers inherit the parent Zygote's asyncio event loop with scheduled tasks.
        # We must cancel all tasks and reset the event loop to prevent socket interference.
        try:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                # Cancel all tasks inherited from parent
                for task in asyncio.all_tasks(loop):
                    task.cancel()
            except RuntimeError:
                pass  # No running loop
            # Create a new event loop for this child process
            asyncio.set_event_loop(asyncio.new_event_loop())
        except Exception:
            pass

        # 3. Re-seed random number generators
        random.seed()

        if "numpy" in sys.modules:
            try:
                import numpy as np

                np.random.seed()
            except Exception:
                pass

    @staticmethod
    def hook_computing(**kwargs: Any) -> None:
        """OpenMP and CUDA reset."""
        if "torch" in sys.modules:
            try:
                import torch

                if torch.cuda.is_available():  # type: ignore
                    torch.cuda.empty_cache()  # type: ignore
            except Exception:
                pass

        # RFC-0011 HPC-001: Restore threading environment post-fork
        # Defaulting to 0 (which usually triggers logical CPU count in BLAS)
        # or explicitly reading cpu_count.
        import multiprocessing

        try:
            cpus = str(multiprocessing.cpu_count())
            for var in [
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            ]:
                if var in os.environ:
                    # Restore to CPU count for workers to ensure performance
                    os.environ[var] = cpus
        except Exception as e:
            LogUtils.log(f"HPC Restoration Warning: {e}")

    @staticmethod
    def hook_telemetry(**kwargs: Any) -> None:
        """Reset spans/trace context."""
        # Placeholder for OpenTelemetry re-init
        pass

    @staticmethod
    def hook_isolation(**kwargs: Any) -> None:
        """P0: Isolated TMPDIR per worker (RFC-0012: No hardcoded /tmp)."""
        import tempfile

        worker_pid = os.getpid()
        # RFC-0012: Use system temp dir instead of hardcoded /tmp
        system_tmp = tempfile.gettempdir()
        worker_base = os.path.join(system_tmp, f"velo-worker-{worker_pid}")

        # P0: Isolated TMPDIR - prevents temp file collisions
        worker_tmp = os.path.join(worker_base, "tmp")
        os.makedirs(worker_tmp, exist_ok=True)
        os.environ["TMPDIR"] = worker_tmp
        os.environ["TMP"] = worker_tmp
        os.environ["TEMP"] = worker_tmp

        # P1: Socket namespace isolation
        os.environ["VELO_WORKER_ID"] = str(worker_pid)
        worker_socket_dir = os.path.join(worker_base, "sockets")
        os.environ["VELO_WORKER_SOCKET_DIR"] = worker_socket_dir
        os.makedirs(worker_socket_dir, exist_ok=True)


# Global hooks registry (singleton access for backward compatibility)
reinit_hooks = ReinitHooks.get_instance()


def post_fork_reinit(keep_fds: set[int] | None = None) -> None:
    """RFC-0011 6A.2: Reset child process state using Hooks Registry."""
    reinit_hooks.run_all(keep_fds=keep_fds)
