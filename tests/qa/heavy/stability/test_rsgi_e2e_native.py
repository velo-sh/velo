import os
import signal
import socket
import subprocess
import textwrap
import time
import uuid
from pathlib import Path

import pytest
import requests


@pytest.fixture
def run_velo_native(isolated_env):
    """Start a real velo process in native RSGI mode."""

    def _run(app_code, env=None, extra_args=None):
        app_path = isolated_env.home / "main.py"
        app_path.write_text(textwrap.dedent(app_code))

        env_vars = os.environ.copy()
        env_vars["PYTHONPATH"] = f"{os.getcwd()}:{env_vars.get('PYTHONPATH', '')}"
        env_vars["VELO_TEST_MODE"] = "1"

        short_id = str(uuid.uuid4())[:8]
        socket_dir = Path(f"/tmp/v-{short_id}")
        socket_dir.mkdir(parents=True, exist_ok=True)
        env_vars["VELO_SOCKET_DIR"] = str(socket_dir)

        if env:
            env_vars.update(env)

        port = isolated_env.next_port()

        stdout_path = isolated_env.home / f"velo_stdout_{short_id}.log"
        stderr_path = isolated_env.home / f"velo_stderr_{short_id}.log"

        stdout_f = open(stdout_path, "w")
        stderr_f = open(stderr_path, "w")

        # We MUST ensure the binary used is the one with granian_native
        # VeloTestEnv already copies the binary to self.velo
        cmd = [isolated_env.velo, "serve", "main:app", "--rsgi", "--port", str(port), "--workers", "1"]
        if extra_args:
            cmd.extend(extra_args)

        proc = subprocess.Popen(
            cmd,
            cwd=isolated_env.home,
            env=env_vars,
            stdout=stdout_f,
            stderr=stderr_f,
            text=True,
            start_new_session=True,
        )

        # Wait for port to be available
        start = time.time()
        success = False
        while time.time() - start < 10:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    success = True
                    break
            except Exception:
                time.sleep(0.5)

        if not success:
            proc.kill()
            stdout_f.close()
            stderr_f.close()
            with open(stderr_path) as f:
                print(f"Server failed to start. Stderr:\n{f.read()}")
            pytest.fail("Velo failed to start in native mode")

        return proc, port, stdout_path, stderr_path, socket_dir, stdout_f, stderr_f

    return _run


@pytest.mark.tier1
def test_rsgi_native_http_basic(run_velo_native):
    """Verify basic HTTP request/response in native RSGI mode."""
    app_code = """
    async def app(scope, proto):
        if scope.proto == 'http':
            proto.response_str(
                200,
                [('content-type', 'application/json')],
                '{"status": "ok", "mode": "native"}'
            )
    """
    proc, port, stdout_p, stderr_p, sdir, out_f, err_f = run_velo_native(app_code)
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["mode"] == "native"
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        out_f.close()
        err_f.close()


@pytest.mark.tier1
def test_rsgi_native_websocket_echo(run_velo_native):
    """Verify WebSocket echo in native RSGI mode."""
    app_code = """
    async def app(scope, proto):
        if scope.proto == 'ws':
            transport = await proto.accept()
            while True:
                message = await transport.receive()
                if message.kind == 0: # Close
                    break
                if message.kind == 2: # Text
                    await transport.send_str(f"echo: {message.data}")
                else: # Bytes
                    await transport.send_bytes(message.data)
    """
    proc, port, stdout_p, stderr_p, sdir, out_f, err_f = run_velo_native(app_code)
    try:
        import websocket

        ws = websocket.create_connection(f"ws://127.0.0.1:{port}/")
        ws.send("hello native")
        result = ws.recv()
        assert result == "echo: hello native"

        ws.send_binary(b"\xde\xad\xbe\xef")
        result = ws.recv()
        assert result == b"\xde\xad\xbe\xef"

        ws.close()
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        out_f.close()
        err_f.close()


def test_rsgi_native_ipc_timeout(run_velo_native):
    """Verify that a hung ASGI app triggers the 10s RSGI IPC timeout."""
    app_code = """
    import asyncio
    async def app(scope, proto):
        if scope.proto == 'http':
            await asyncio.sleep(15) # Exceeds 10s timeout
            proto.response_str(200, [], 'this should not be sent')
    """
    proc, port, stdout_p, stderr_p, sdir, out_f, err_f = run_velo_native(app_code)
    try:
        import time

        import requests

        start = time.time()
        # Request should return 500 after ~10s
        resp = requests.get(f"http://127.0.0.1:{port}/", timeout=20)
        duration = time.time() - start

        assert resp.status_code == 500
        assert 10 <= duration <= 13  # Allow for some overhead
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        out_f.close()
        err_f.close()


def test_rsgi_native_header_timeout(run_velo_native):
    """Verify that slow headers trigger the 5s header read timeout."""
    app_code = """
    async def app(scope, proto):
        proto.response_str(200, [], 'ok')
    """
    proc, port, stdout_p, stderr_p, sdir, out_f, err_f = run_velo_native(app_code)
    try:
        import socket
        import time

        s = socket.create_connection(("127.0.0.1", port))
        s.send(b"GET / HTTP/1.1\r\n")
        time.sleep(7)  # Exceeds 5s header timeout
        try:
            s.send(b"Host: localhost\r\n\r\n")
            # Connection should have been closed by server
            s.settimeout(2)
            data = s.recv(1024)
            # If server closed, recv returns b'' or raises error
            assert data == b""
        except (TimeoutError, ConnectionResetError, BrokenPipeError):
            pass  # Success: connection closed
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        out_f.close()
        err_f.close()
