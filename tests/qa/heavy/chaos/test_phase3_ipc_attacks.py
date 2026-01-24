from __future__ import annotations

"""
Velo QA: Phase 3 IPC/Socket Attack Tests (IPC-xxx)
===================================================
Adversarial tests targeting Zygote IPC mechanism.

Goal: Break the socket-based IPC with fuzzing and exploitation!
"""

import os
import socket
import threading
import time

from phase3_harness import (
    ZygoteTestEnv,
)
from qa_harness import assert_no_crash, run_velo


class TestIPCAttacks:
    """IPC-xxx: Socket/IPC attack tests."""

    def test_ipc_001_socket_no_permission(self):
        """
        IPC-001: Socket path has no write permission.

        Attack: chmod 000 on socket directory.
        Expected: Start fails with clear error.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create socket dir and remove permissions
            env.socket_path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(str(env.socket_path.parent), 0o000)

            result = run_velo(
                ["zygote", "start"],
                cwd=env.path,
                env={"VELO_SOCKET_DIR": str(env.socket_path.parent)},
                timeout=10,
            )

            assert_no_crash(result)
            # Should fail with permission error
            assert not result.success, "Should fail with no socket permission"

        finally:
            # Restore permissions for cleanup
            try:
                os.chmod(str(env.socket_path.parent), 0o755)
            except Exception:
                pass
            env.cleanup()

    def test_ipc_002_socket_is_directory(self):
        """
        IPC-002: Socket path is a directory.

        Attack: Directory at socket path.
        Expected: Error, cleanup, retry or fail clearly.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create socket path as directory
            env.socket_path.parent.mkdir(parents=True, exist_ok=True)
            env.socket_path.mkdir(exist_ok=True)

            result = run_velo(
                ["zygote", "start"],
                cwd=env.path,
                env={"VELO_SOCKET_DIR": str(env.socket_path.parent)},
                timeout=10,
            )

            assert_no_crash(result)
            # Should handle gracefully
        finally:
            # Cleanup directory at socket path
            try:
                if env.socket_path.is_dir():
                    env.socket_path.rmdir()
            except Exception:
                pass
            env.cleanup()

    def test_ipc_004_socket_garbage_data(self):
        """
        IPC-004: Send garbage bytes to Zygote socket.

        Attack: Random bytes to socket.
        Expected: Ignore garbage, no crash.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Start Zygote first
            start_result = run_velo(
                ["zygote", "start"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=10
            )

            if start_result.success and env.socket_path.exists():
                # Send garbage
                garbage = os.urandom(1024)
                env.send_raw_ipc(garbage, timeout=2)

                # Zygote should still be running
                status = run_velo(
                    ["zygote", "status"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=5
                )
                assert_no_crash(status)
        finally:
            env.cleanup()

    def test_ipc_006_incomplete_message(self):
        """
        IPC-006: Send truncated/incomplete message.

        Attack: Partial IPC message.
        Expected: Timeout and error, no hang.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Start Zygote
            start_result = run_velo(
                ["zygote", "start"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=10
            )

            if start_result.success and env.socket_path.exists():
                # Send partial message
                partial = b'{"cmd": "run", "script":'  # Incomplete JSON
                env.send_raw_ipc(partial, timeout=2)

                # Should timeout, not hang forever
                # Zygote should survive
                status = run_velo(
                    ["zygote", "status"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=5
                )
                assert_no_crash(status)
        finally:
            env.cleanup()

    def test_ipc_007_huge_message(self):
        """
        IPC-007: Send huge message to socket.

        Attack: 10MB IPC message.
        Expected: Reject, no OOM crash.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Start Zygote
            start_result = run_velo(
                ["zygote", "start"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=10
            )

            if start_result.success and env.socket_path.exists():
                # Send huge message
                huge_data = b"A" * (10 * 1024 * 1024)  # 10MB

                try:
                    env.send_raw_ipc(huge_data, timeout=5)
                except Exception:
                    pass  # Expected to fail

                # Zygote should survive
                time.sleep(0.5)
                status = run_velo(
                    ["zygote", "status"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=5
                )
                # Either recovers or we get clear error
                assert_no_crash(status)
        finally:
            env.cleanup()

    def test_ipc_008_concurrent_connections(self):
        """
        IPC-008: Many concurrent socket connections.

        Attack: 20 parallel connections.
        Expected: Correct serialization, no race conditions.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Start Zygote
            start_result = run_velo(
                ["zygote", "start"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=10
            )

            if start_result.success and env.socket_path.exists():
                results: list[tuple[str, bytes | str]] = []

                def connect_and_send():
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(2)
                        sock.connect(str(env.socket_path))
                        sock.sendall(b"ping")
                        response = sock.recv(1024)
                        sock.close()
                        results.append(("ok", response))
                    except Exception as e:
                        results.append(("error", str(e)))

                # 20 concurrent connections
                threads = [threading.Thread(target=connect_and_send) for _ in range(20)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)

                # Zygote should survive
                status = run_velo(
                    ["zygote", "status"], cwd=env.path, env={"VELO_SOCKET_DIR": str(env.socket_path.parent)}, timeout=5
                )
                assert_no_crash(status)
        finally:
            env.cleanup()
