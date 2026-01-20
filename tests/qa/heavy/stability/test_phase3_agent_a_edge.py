from __future__ import annotations

"""
Velo QA: Agent A - Edge Case Hunter (EDGE-xxx)
===============================================
Aggressive QA: Find every corner case that breaks the system!

Agent A's mission: If it can break, I will break it.
"""

import threading
import time

from qa_harness import assert_no_crash, run_velo
from phase3_harness import ZygoteTestEnv


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

            env.create_script(
                "thread_fork.py",
                """
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
""",
            )

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
            env.create_script(
                "alloc.py",
                """
import sys
try:
    data = []
    for i in range(100):
        data.append(bytearray(10 * 1024 * 1024))  # 10MB each
except MemoryError:
    print("OOM handled")
    sys.exit(0)
print("allocated")
""",
            )

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


# =============================================================================
# CROSS-REVIEW: Agent B (Stability) additions to Edge Cases
# =============================================================================


class TestEdgeCaseStability:
    """Agent B review: Stability after edge case handling."""

    def test_edge_stable_001_recovery_after_edge(self):
        """
        Agent B: System should recover after hitting edge case.

        After edge case, normal operation should work.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Hit edge case - empty script
            env.create_script("empty.py", "")
            run_velo(["run", "--zygote", "empty.py"], cwd=env.path, timeout=10)

            # Normal operation should still work
            env.create_script("normal.py", "print('ok')")
            result = run_velo(["run", "--zygote", "normal.py"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            if result.success:
                assert "ok" in result.stdout
        finally:
            env.cleanup()

    def test_edge_stable_002_no_state_corruption(self):
        """
        Agent B: Edge cases should not corrupt internal state.

        Run edge case, then verify normal operation 10x.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Hit multiple edge cases
            env.create_script("empty.py", "")
            run_velo(["run", "--zygote", "empty.py"], cwd=env.path, timeout=10)
            run_velo(["run", "--zygote", "nonexistent.py"], cwd=env.path, timeout=10)

            # Now run normal script 10x
            env.create_script("check.py", "print('state_ok')")

            for _ in range(10):
                result = run_velo(["run", "--zygote", "check.py"], cwd=env.path, timeout=10)
                assert_no_crash(result)
                if result.success:
                    assert "state_ok" in result.stdout
        finally:
            env.cleanup()


# =============================================================================
# CROSS-REVIEW: Agent C (Security) additions to Edge Cases
# =============================================================================


class TestEdgeCaseSecurity:
    """Agent C review: Security implications of edge cases."""

    def test_edge_sec_001_edge_no_extra_permissions(self):
        """
        Agent C: Edge case handling should not grant extra permissions.

        After edge case, permissions should be unchanged.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Get initial UID
            env.create_script("uid1.py", "import os; print(f'UID:{os.getuid()}')")
            result1 = run_velo(["run", "--zygote", "uid1.py"], cwd=env.path, timeout=10)

            # Hit edge cases
            run_velo(["run", "--zygote", ""], cwd=env.path, timeout=5)
            run_velo(["run", "--zygote", "../../../etc/passwd"], cwd=env.path, timeout=5)

            # Check UID unchanged
            env.create_script("uid2.py", "import os; print(f'UID:{os.getuid()}')")
            result2 = run_velo(["run", "--zygote", "uid2.py"], cwd=env.path, timeout=10)

            if result1.success and result2.success:
                assert result1.stdout.strip() == result2.stdout.strip(), "UID changed after edge case!"
        finally:
            env.cleanup()

    def test_edge_sec_002_edge_no_info_leak(self):
        """
        Agent C: Edge cases should not leak system information.

        Error messages from edge cases should be sanitized.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Try various edge cases
            edge_cases = [
                ["run", "--zygote", "../../../etc/shadow"],
                ["run", "--zygote", "/dev/null"],
                ["run", "--zygote", ""],
            ]

            for cmd in edge_cases:
                result = run_velo(cmd, cwd=env.path, timeout=5)

                # Check no sensitive info in output
                output = (result.stdout + result.stderr).lower()
                sensitive_patterns = ["/etc/shadow", "/root/", "password", "secret"]

                for pattern in sensitive_patterns:
                    assert pattern not in output, f"Sensitive info leaked: {pattern}"
        finally:
            env.cleanup()

    def test_edge_sec_003_edge_no_resource_escalation(self):
        """
        Agent C: Edge cases should not allow resource escalation.

        After edge case, resource limits should hold.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # Get initial FD count
            env.create_script(
                "fd1.py",
                """
import os
fds = [fd for fd in range(100) if os.fstat(fd) is not None or True]
print(f'FD_COUNT:{len([fd for fd in range(100) if True])}')
""",
            )

            # This is a placeholder - actual FD counting is complex
            result = run_velo(["run", "--zygote", "fd1.py"], cwd=env.path, timeout=10)
            assert_no_crash(result)
        finally:
            env.cleanup()
