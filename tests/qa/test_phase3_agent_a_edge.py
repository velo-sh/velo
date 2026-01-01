"""
Velo QA: Agent A - Edge Case Hunter (EDGE-xxx)
===============================================
Aggressive QA: Find every corner case that breaks the system!

Agent A's mission: If it can break, I will break it.
"""

import os
import signal
import time
import threading
import pytest
from pathlib import Path

from test_harness import run_velo, assert_no_crash
from test_phase3_harness import ZygoteTestEnv, count_zombie_processes


class TestEdgeCasesLifecycle:
    """EDGE-ZYG-xxx: Lifecycle edge cases."""

    def test_edge_zyg_001_start_during_shutdown(self):
        """
        EDGE-ZYG-001: Start Zygote while another is shutting down.
        
        Attack: Race between start and stop.
        Expected: One wins cleanly, no corruption.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Start Zygote
            run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            
            results = []
            
            def start_cmd():
                r = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
                results.append(("start", r))
            
            def stop_cmd():
                r = run_velo(["zygote", "stop"], cwd=env.path, timeout=10)
                results.append(("stop", r))
            
            # Race start and stop
            t1 = threading.Thread(target=stop_cmd)
            t2 = threading.Thread(target=start_cmd)
            t1.start()
            time.sleep(0.1)
            t2.start()
            t1.join(timeout=15)
            t2.join(timeout=15)
            
            # No crashes
            for cmd, result in results:
                assert_no_crash(result)
        finally:
            env.cleanup()

    def test_edge_zyg_004_zero_workers_limit(self):
        """
        EDGE-ZYG-004: Configure max_workers = 0.
        
        Attack: Invalid configuration value.
        Expected: Error or use default.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            config = """
[zygote]
max_workers = 0
"""
            env.create_velo_config(config)
            
            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            assert_no_crash(result)
            # Should reject or use default
        finally:
            env.cleanup()


class TestEdgeCasesFork:
    """EDGE-FORK-xxx: Fork edge cases."""

    def test_edge_fork_002_thread_plus_fork(self):
        """
        EDGE-FORK-002: Multi-threaded script with fork.
        
        Attack: Thread + fork is dangerous (deadlock risk).
        Expected: Handle gracefully or warn.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            env.create_script("thread_fork.py", """
import threading
import os
import sys

def worker():
    pass

# Start threads
threads = [threading.Thread(target=worker) for _ in range(5)]
for t in threads:
    t.start()

# Now fork (dangerous!)
try:
    if os.fork() == 0:
        sys.exit(0)
except Exception as e:
    print(f"Fork failed: {e}")

for t in threads:
    t.join()
print("done")
""")
            
            result = run_velo(["run", "--zygote", "thread_fork.py"], cwd=env.path, timeout=30)
            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_edge_fork_005_oom_during_fork(self):
        """
        EDGE-FORK-005: Simulate OOM condition.
        
        Attack: Low memory situation during fork.
        Expected: Graceful failure, Zygote survives.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Script that allocates memory
            env.create_script("alloc.py", """
import sys
try:
    data = []
    for i in range(100):
        data.append(bytearray(10 * 1024 * 1024))  # 10MB each
except MemoryError:
    print("OOM handled")
    sys.exit(0)
print("allocated")
""")
            
            # Run with zygote
            result = run_velo(["run", "--zygote", "alloc.py"], cwd=env.path, timeout=60)
            assert_no_crash(result)
        finally:
            env.cleanup()


class TestEdgeCasesIPC:
    """EDGE-IPC-xxx: IPC edge cases."""

    def test_edge_ipc_001_socket_eof(self):
        """
        EDGE-IPC-001: Connect, send, close immediately.
        
        Attack: Rapid connect/disconnect.
        Expected: No crash.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            import socket
            
            run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            
            if env.socket_path.exists():
                for _ in range(10):
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(0.5)
                        sock.connect(str(env.socket_path))
                        sock.sendall(b"test")
                        sock.close()
                    except Exception:
                        pass
                
                # Zygote should survive
                status = run_velo(["zygote", "status"], cwd=env.path, timeout=5)
                assert_no_crash(status)
        finally:
            env.cleanup()

    def test_edge_ipc_002_half_open_connection(self):
        """
        EDGE-IPC-002: Connect but never send.
        
        Attack: Connection leak / resource exhaustion.
        Expected: Timeout, cleanup.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            import socket
            
            run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            
            if env.socket_path.exists():
                sockets = []
                for _ in range(5):
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(0.5)
                        sock.connect(str(env.socket_path))
                        sockets.append(sock)
                        # Don't send anything!
                    except Exception:
                        pass
                
                time.sleep(1)
                
                # Close all
                for sock in sockets:
                    sock.close()
                
                # Zygote should survive
                status = run_velo(["zygote", "status"], cwd=env.path, timeout=5)
                assert_no_crash(status)
        finally:
            env.cleanup()

    def test_edge_ipc_003_unicode_path(self):
        """
        EDGE-IPC-003: Socket path with unicode/emoji.
        
        Attack: Non-ASCII path.
        Expected: Handle or reject clearly.
        """
        # This test requires custom socket path which may not be configurable
        # Placeholder for when feature is available
        pass

    def test_edge_ipc_005_symlink_socket(self):
        """
        EDGE-IPC-005: Socket path is a symlink.
        
        Attack: Redirect via symlink.
        Expected: Follow or reject.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            
            # Create symlink at socket path pointing elsewhere
            env.socket_path.parent.mkdir(parents=True, exist_ok=True)
            target = env.path / "real_socket"
            
            # Create symlink
            try:
                env.socket_path.symlink_to(target)
            except Exception:
                pass  # May fail on some systems
            
            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)
            assert_no_crash(result)
        finally:
            env.cleanup()
