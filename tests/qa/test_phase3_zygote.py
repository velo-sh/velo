"""
Phase 3 Zygote QA Tests

TDD: These tests verify the Zygote Python module functionality.

Test Categories:
- ZYG-*: Core Zygote functionality
"""

import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

import pytest

# Mark entire module as Zygote flaky - skip in CI due to timing/resource issues
pytestmark = [pytest.mark.zygote_flaky, pytest.mark.tier2]

# Path to velo_zygote module
VELO_ROOT = Path(__file__).parent.parent.parent
ZYGOTE_MAIN = VELO_ROOT / "velo_zygote" / "main.py"


class ZygoteTestHelper:
    """Helper class for Zygote testing."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, preload: list[str] | None = None) -> None:
        """Start Zygote process."""
        cmd = [sys.executable, str(ZYGOTE_MAIN), "--socket", str(self.socket_path)]
        if preload:
            cmd.extend(["--preload"] + preload)

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for socket to be created
        for _ in range(50):
            if self.process.poll() is not None:
                assert self.process.stderr is not None
                stderr = self.process.stderr.read().decode()
                raise RuntimeError(
                    f"Zygote process died early! RC={self.process.returncode}, Stderr: {stderr}"
                ) from None
            if self.socket_path.exists():
                break
            time.sleep(0.1)
        else:
            assert self.process.stderr is not None
            raise RuntimeError(
                f"Zygote socket not created in time. Stderr: {self.process.stderr.read().decode()}"
            ) from None

    def connect(self) -> socket.socket:
        """Connect to Zygote socket."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(self.socket_path))

        # Read READY response (MessagePack Protocol)
        # 1. Read Length (4 bytes)
        len_data = self._recv_exact(sock, 4)
        total_len = int.from_bytes(len_data, "little")

        # 2. Read Version (1 byte)
        self._recv_exact(sock, 1)

        # 3. Read Payload
        payload_len = total_len - 1
        payload_data = self._recv_exact(sock, payload_len)

        # Decode
        response = self._unpack(payload_data)
        assert response.get("type") == "Ready"

        return sock

    def send_command(self, sock: socket.socket, cmd: dict[str, Any]) -> dict[str, Any]:
        """Send command and get response."""
        # Encode (MessagePack)
        # 1. Payload
        payload = self._pack(cmd)

        # 2. Key components
        total_len = 1 + len(payload)
        header = total_len.to_bytes(4, "little")
        version = b"\x01"

        # Send
        sock.sendall(header + version + payload)

        # Receive Response
        len_data = self._recv_exact(sock, 4)
        total_len = int.from_bytes(len_data, "little")

        self._recv_exact(sock, 1)

        payload_len = total_len - 1
        payload_data = self._recv_exact(sock, payload_len)

        return self._unpack(payload_data)

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        data = b""
        sock.settimeout(5.0)  # Defensive timeout (RFC-0010 security)
        try:
            while len(data) < n:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    raise EOFError("Socket closed")
                data += chunk
            return data
        except TimeoutError:
            raise RuntimeError(f"Socket timeout waiting for {n} bytes") from None
        finally:
            sock.settimeout(None)

    def _pack(self, msg: dict[str, Any]) -> bytes:
        try:
            import msgpack

            return cast(bytes, msgpack.packb(msg, use_bin_type=True))
        except ImportError:
            # Fallback to internal serializer if available or simple json mapping (risky but maybe works for simple types)
            # Better to import from serializer
            sys.path.append(str(VELO_ROOT))
            from velo_zygote.serializer import packer

            return packer(msg)

    def _unpack(self, data: bytes) -> dict[str, Any]:
        try:
            import msgpack

            result = msgpack.unpackb(data, raw=False)
            return result if isinstance(result, dict) else {}
        except ImportError:
            sys.path.append(str(VELO_ROOT))
            from velo_zygote.serializer import unpacker

            result = unpacker(data)
            return result if isinstance(result, dict) else {}

    def stop(self) -> None:
        """Stop Zygote process."""
        if self.process:
            try:
                sock = self.connect()
                self.send_command(sock, {"type": "Shutdown"})
                sock.close()
            except Exception:
                pass

            self.process.terminate()
            self.process.wait(timeout=5)


class TestZygoteReady:
    """ZYG-001: Zygote process starts and signals ready."""

    def test_zygote_starts_and_signals_ready(self, tmp_path):
        """Test that Zygote starts and sends READY signal."""
        # Use /tmp to avoid AF_UNIX path length limits on macOS
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            socket_path = Path(td) / "test.sock"
            helper = ZygoteTestHelper(socket_path)

            try:
                helper.start()
                sock = helper.connect()  # This verifies READY was received
                sock.close()
            finally:
                helper.stop()

    def test_zygote_preloads_modules(self, tmp_path):
        """Test that Zygote pre-loads specified modules."""
        # Use /tmp to avoid AF_UNIX path length limits on macOS
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            socket_path = Path(td) / "test.sock"
            helper = ZygoteTestHelper(socket_path)

            try:
                # Pre-load a standard library module
                helper.start(preload=["json", "os"])
                sock = helper.connect()
                sock.close()
            finally:
                helper.stop()


class TestZygoteFork:
    """ZYG-002: Zygote fork functionality."""

    def test_fork_executes_script(self, tmp_path):
        """Test that Fork command executes a script."""
        # Use /tmp to avoid AF_UNIX path length limits on macOS
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            socket_path = Path(td) / "test.sock"
            output_file = tmp_path / "output.txt"

            # Create test script
            script_path = tmp_path / "test_script.py"
            script_path.write_text(
                f"""
with open('{output_file}', 'w') as f:
    f.write('hello from worker')
"""
            )

            helper = ZygoteTestHelper(socket_path)

            try:
                helper.start()
                sock = helper.connect()

                # Send Fork command
                response = helper.send_command(sock, {"type": "Fork", "script_path": str(script_path), "args": []})

                assert response.get("type") == "Forked"
                assert "worker_pid" in response

                # Wait for worker to complete
                time.sleep(0.5)

                # Verify script executed
                assert output_file.exists()
                assert output_file.read_text() == "hello from worker"

                sock.close()
            finally:
                helper.stop()

    def test_fork_with_args(self, tmp_path):
        """Test that Fork command passes arguments to script."""
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            socket_path = Path(td) / "test.sock"
            output_file = tmp_path / "args.txt"

            # Create test script that writes sys.argv
            script_path = tmp_path / "test_args.py"
            script_path.write_text(
                f"""
import sys
with open('{output_file}', 'w') as f:
    f.write(' '.join(sys.argv[1:]))
"""
            )

            helper = ZygoteTestHelper(socket_path)

            try:
                helper.start()
                sock = helper.connect()

                # Send Fork command with args
                response = helper.send_command(
                    sock,
                    {
                        "type": "Fork",
                        "script_path": str(script_path),
                        "args": ["--arg1", "value1"],
                    },
                )

                assert response.get("type") == "Forked"

                # Wait for worker to complete
                time.sleep(0.5)

                # Verify args were passed
                assert output_file.exists()
                assert output_file.read_text() == "--arg1 value1"

                sock.close()
            finally:
                helper.stop()

    def test_fork_nonexistent_script(self, tmp_path):
        """Test that Fork returns error for nonexistent script."""
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            socket_path = Path(td) / "test.sock"
            helper = ZygoteTestHelper(socket_path)

            try:
                helper.start()
                sock = helper.connect()

                # Send Fork command for nonexistent script
                response = helper.send_command(
                    sock,
                    {
                        "type": "Fork",
                        "script_path": "/nonexistent/script.py",
                        "args": [],
                    },
                )

                assert response.get("type") == "Error"
                assert "not found" in response.get("message", "").lower()

                sock.close()
            finally:
                helper.stop()


class TestZygoteShutdown:
    """ZYG-003: Zygote shutdown functionality."""

    def test_shutdown_cleans_up_socket(self, tmp_path):
        """Test that Shutdown command cleans up socket file."""
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            socket_path = Path(td) / "test.sock"
            helper = ZygoteTestHelper(socket_path)

            try:
                helper.start()
                assert socket_path.exists()

                sock = helper.connect()
                helper.send_command(sock, {"type": "Shutdown"})
                sock.close()

                # Wait for cleanup
                time.sleep(0.5)

                # Socket should be removed
                assert not socket_path.exists()
            finally:
                if helper.process:
                    helper.process.terminate()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
