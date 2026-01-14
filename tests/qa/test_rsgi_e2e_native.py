import pytest
import subprocess
import time
import socket
import os
import sys
from pathlib import Path
import textwrap
import signal
import uuid
import requests
import json

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
            start_new_session=True
        )
        
        # Wait for port to be available
        start = time.time()
        success = False
        while time.time() - start < 10:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    success = True
                    break
            except:
                time.sleep(0.5)
        
        if not success:
            proc.kill()
            stdout_f.close()
            stderr_f.close()
            with open(stderr_path, "r") as f:
                print(f"Server failed to start. Stderr:\n{f.read()}")
            pytest.fail("Velo failed to start in native mode")
            
        return proc, port, stdout_path, stderr_path, socket_dir, stdout_f, stderr_f
    return _run

@pytest.mark.tier1
def test_rsgi_native_http_basic(run_velo_native):
    """Verify basic HTTP request/response in native RSGI mode."""
    app_code = """
    async def app(scope, receive, send):
        if scope['type'] == 'http':
            await send({
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'application/json')],
            })
            await send({
                'type': 'http.response.body',
                'body': b'{"status": "ok", "mode": "native"}',
                'more_body': False
            })
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
    async def app(scope, receive, send):
        if scope['type'] == 'websocket':
            while True:
                message = await receive()
                if message['type'] == 'websocket.connect':
                    await send({'type': 'websocket.accept'})
                elif message['type'] == 'websocket.receive':
                    text = message.get('text')
                    if text:
                        await send({'type': 'websocket.send', 'text': f"echo: {text}"})
                    else:
                        data = message.get('bytes')
                        await send({'type': 'websocket.send', 'bytes': data})
                elif message['type'] == 'websocket.disconnect':
                    break
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
