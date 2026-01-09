"""
Velo Lifecycle Management
"""
import os
import sys
import time
import signal
import random
import threading
from typing import Dict, Tuple, Any, List, Optional, Set
try:
    from .utils import LogUtils
except (ImportError, ValueError):
    from utils import LogUtils

class WorkerRegistry:
    """Layer 3: State Management - Tracks worker lifecycle."""
    def __init__(self, worker_ttl: int = 3600):
        self.workers: Dict[int, Tuple[float, Any]] = {} # pid -> (start_time, metadata)
        self.worker_ttl = worker_ttl

    def add(self, pid: int, metadata: Any = None):
        self.workers[pid] = (time.time(), metadata)

    def remove(self, pid: int):
        self.workers.pop(pid, None)

    def is_alive(self, pid: int) -> bool:
        if pid not in self.workers:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            self.remove(pid)
            return False

    def get_stats(self) -> Dict:
        return {
            "worker_count": len(self.workers),
            "pids": list(self.workers.keys())
        }

    @staticmethod
    def start_guardian(parent_pid: int, ttl: int, monitor_parent: bool = True):
        """Guardian thread to prevent orphans."""
        def guardian():
            while True:
                time.sleep(10)
                # 1. Check parent
                if monitor_parent:
                    try:
                        os.kill(parent_pid, 0)
                    except ProcessLookupError:
                        LogUtils.log("Parent process died. Zygote exiting.")
                        os._exit(0)
                
                # Check for kill signal file or other termination conditions if needed
        
        t = threading.Thread(target=guardian, daemon=True)
        t.start()

    def kill_all(self):
        """Emergency cleanup of all workers."""
        for pid in list(self.workers.keys()):
            try:
                os.kill(pid, signal.SIGKILL)
            except: pass
        self.workers.clear()

    def reap_stale(self):
        """Cleanup logic for timed-out or missing workers."""
        now = time.time()
        for pid, (start_time, _) in list(self.workers.items()):
            if now - start_time > self.worker_ttl:
                try:
                    os.kill(pid, signal.SIGKILL)
                except: pass
                self.remove(pid)
            elif not self.is_alive(pid):
                self.remove(pid)

class ReinitHooks:
    """Layer 3: Hook-based Re-initialization system."""
    def __init__(self):
        self.hooks = []

    def register(self, hook_func):
        self.hooks.append(hook_func)

    def run_all(self, *args, **kwargs):
        for hook in self.hooks:
            try:
                hook(*args, **kwargs)
            except Exception as e:
                LogUtils.log(f"Hook Failure: {hook.__name__}: {e}")

# Global hooks registry
reinit_hooks = ReinitHooks()

def hook_security(keep_fds: Optional[Set[int]] = None):
    """Industrial Grade Cord-Cutting."""
    # 1. Close all non-standard file descriptors
    try:
        from .constants import PATH_LINUX_FD_DIR, PATH_MACOS_FD_DIR
    except (ImportError, ValueError):
        from constants import PATH_LINUX_FD_DIR, PATH_MACOS_FD_DIR
    
    fd_dir = PATH_MACOS_FD_DIR if sys.platform == 'darwin' else PATH_LINUX_FD_DIR
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
        LogUtils.log(f"Forensic Cleanup Warning: Failed to list descriptors in '{fd_dir}': {e}. Falling back to range scan.")
        # Fallback for systems without /proc or /dev/fd
        for fd in range(3, 1024):
            if keep_fds is None or fd not in keep_fds:
                try: os.close(fd)
                except: pass

    # 2. Reset signal handlers
    for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGCHLD]:
        try: signal.signal(sig, signal.SIG_DFL)
        except: pass

    # 3. Re-seed random number generators
    random.seed()
    if 'numpy' in sys.modules:
        try:
            import numpy as np
            np.random.seed()
        except: pass

def hook_computing(**kwargs):
    """OpenMP and CUDA reset."""
    if 'torch' in sys.modules:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except: pass

def hook_telemetry(**kwargs):
    """Reset spans/trace context."""
    # Placeholder for OpenTelemetry re-init
    pass

reinit_hooks.register(hook_security)
reinit_hooks.register(hook_computing)
reinit_hooks.register(hook_telemetry)

def post_fork_reinit(keep_fds: Optional[Set[int]] = None):
    """RFC-0011 6A.2: Reset child process state using Hooks Registry."""
    reinit_hooks.run_all(keep_fds=keep_fds)
