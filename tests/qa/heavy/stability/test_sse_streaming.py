import os
import socket
import subprocess
import textwrap
import time
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def run_velo_e2e(isolated_env):
    """Start a real velo process with a real python worker."""

    def _run(app_path, env=None, extra_args=None):
        env_vars = os.environ.copy()
        env_vars["PYTHONPATH"] = f"{os.getcwd()}:{env_vars.get('PYTHONPATH', '')}"
        env_vars["VELO_TEST_MODE"] = "1"

        short_id = str(uuid.uuid4())[:8]
        socket_dir = Path(f"/tmp/v-{short_id}")
        socket_dir.mkdir(parents=True, exist_ok=True)
        env_vars["VELO_SOCKET_DIR"] = str(socket_dir)

        debug_log = isolated_env.home / f"worker_{short_id}.log"
        env_vars["VELO_WORKER_DEBUG_LOG"] = str(debug_log)

        if env:
            env_vars.update(env)

        port = isolated_env.next_port()
        cwd = app_path.parent
        app_module = app_path.stem

        stdout_path = isolated_env.home / f"velo_stdout_{short_id}.log"
        stderr_path = isolated_env.home / f"velo_stderr_{short_id}.log"

        stdout_f = open(stdout_path, "w")
        stderr_f = open(stderr_path, "w")

        cmd = [isolated_env.velo, "serve", f"{app_module}:app", "--rsgi", "--port", str(port)]
        if extra_args:
            cmd.extend(extra_args)

        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env_vars, stdout=stdout_f, stderr=stderr_f, text=True, start_new_session=True
        )
        return proc, port, stdout_path, stderr_path, socket_dir, debug_log

    return _run


@pytest.mark.tier1
def test_sse_streaming_realtime(isolated_env, run_velo_e2e):
    """[DEF-72-C05] Verify SSE streaming chunks are received in real-time."""
    app_code = """
    import asyncio
    async def app(scope, receive, send):
        if scope['type'] == 'http':
            await send({
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'text/event-stream')],
            })
            for i in range(5):
                await send({
                    'type': 'http.response.body',
                    'body': f"data: chunk {i}\\n\\n".encode(),
                    'more_body': True
                })
                await asyncio.sleep(0.5)
            await send({
                'type': 'http.response.body',
                'body': b"",
                'more_body': False
            })
    """
    app_path = isolated_env.home / "app_sse.py"
    app_path.write_text(textwrap.dedent(app_code))

    proc, port, stdout_p, stderr_p, socket_dir, debug_log = run_velo_e2e(app_path)
    try:
        time.sleep(5)
        url = f"http://127.0.0.1:{port}/"

        # We use a raw socket to read line by line and measure timing
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")

        start_time = time.time()
        received_chunks = []

        # Read headers
        # Read body chunks with raw recv to avoid any buffering logic
        while len(received_chunks) < 5:
            data = s.recv(4096)
            if not data:
                break
            # Only count chunks that contain "data:"
            if b"data:" in data:
                elapsed = time.time() - start_time
                print(f"Received data at {elapsed:.2f}s: {data}")
                received_chunks.append(elapsed)

        assert len(received_chunks) == 5
        # Verify chunks arrived incrementally (at least 0.3s apart)
        for i in range(1, 5):
            diff = received_chunks[i] - received_chunks[i - 1]
            print(f"Diff {i}: {diff:.2f}s")
            assert diff >= 0.3, f"Chunk {i} arrived too quickly after chunk {i - 1} ({diff:.2f}s), buffering suspected!"

        print("Verified Real-time SSE Streaming!")

    finally:
        import os
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except:
            pass
        proc.wait()
