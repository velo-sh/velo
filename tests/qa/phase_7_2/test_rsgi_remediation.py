import pytest
import subprocess
import time
import socket
import os
import msgpack
import sys
from pathlib import Path
import urllib.request
import textwrap
import signal
import uuid

@pytest.fixture
def run_velo_e2e(isolated_env):
    """Start a real velo process with a real python worker."""
    def _run(app_path, env=None):
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
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env_vars,
            stdout=stdout_f,
            stderr=stderr_f,
            text=True,
            start_new_session=True
        )
        return proc, port, stdout_path, stderr_path, socket_dir, debug_log
    return _run

class TestRsgiRemediation:
    """Verification for DEF-72-C01 and DEF-72-C02."""

    @pytest.mark.tier1
    def test_query_string_preservation(self, isolated_env, run_velo_e2e):
        """[DEF-72-C01] Verify query string is preserved."""
        app_code = """
async def app(scope, receive, send):
    if scope['type'] == 'http':
        query_string = scope.get('query_string', b'').decode()
        path = scope.get('path', '')
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'text/plain')],
        })
        await send({
            'type': 'http.response.body',
            'body': f"PATH:{path}|QUERY:{query_string}".encode(),
        })
"""
        app_path = isolated_env.home / "app_qs.py"
        app_path.write_text(textwrap.dedent(app_code))
        
        proc, port, stdout_p, stderr_p, socket_dir, debug_log = run_velo_e2e(app_path)
        try:
            time.sleep(5)
            qs = "foo=bar&baz=123+456%20789"
            url = f"http://127.0.0.1:{port}/test/path?{qs}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read().decode()
                
            assert "/test/path" in body
            assert f"QUERY:{qs}" in body
            print(f"Verified Query String: {body}")
            
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            import shutil
            shutil.rmtree(socket_dir, ignore_errors=True)

    @pytest.mark.tier1
    def test_dependency_shadowing_protection(self, isolated_env, run_velo_e2e):
        """[DEF-72-C02] Verify user cannot shadow msgpack."""
        app_dir = isolated_env.home / "shadow_test"
        app_dir.mkdir(parents=True, exist_ok=True)
        
        fake_msgpack = app_dir / "msgpack.py"
        fake_msgpack.write_text("raise ImportError('SHADOWED!')")
        
        app_code = """
import msgpack
async def app(scope, receive, send):
    if scope['type'] == 'http':
        is_real = hasattr(msgpack, 'packb')
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'text/plain')],
        })
        await send({
            'type': 'http.response.body',
            'body': f"REAL_MSGPACK:{is_real}".encode(),
        })
"""
        app_path = app_dir / "app_shadow.py"
        app_path.write_text(textwrap.dedent(app_code))
        
        proc, port, stdout_p, stderr_p, socket_dir, debug_log = run_velo_e2e(app_path)
        try:
            time.sleep(5)
            url = f"http://127.0.0.1:{port}/"
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    body = resp.read().decode()
            except Exception as e:
                print(f"Request failed: {e}")
                print(f"--- VELO STDERR ---\n{stderr_p.read_text()}")
                if debug_log.exists():
                    print(f"--- WORKER DEBUG LOG ---\n{debug_log.read_text()}")
                else:
                    print("--- WORKER DEBUG LOG MISSING ---")
                raise e
                
            assert "REAL_MSGPACK:True" in body
            print(f"Verified Shadowing Protection: {body}")
            
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            import shutil
            shutil.rmtree(socket_dir, ignore_errors=True)
