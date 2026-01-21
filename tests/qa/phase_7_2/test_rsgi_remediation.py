import os
import signal
import subprocess
import textwrap
import time
import urllib.request
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

    @pytest.mark.tier1
    def test_native_sovereignty_uvicorn_absence(self, isolated_env, run_velo_e2e):
        """[RFC-0019] Verify Architectural Sovereignty: uvicorn MUST NOT be pre-loaded in RSGI mode."""
        app_code = """
        import sys
        async def app(scope, receive, send):
            if scope['type'] == 'http':
                # Check if uvicorn is in sys.modules
                uvicorn_loaded = 'uvicorn' in sys.modules
                await send({
                    'type': 'http.response.start',
                    'status': 200,
                    'headers': [(b'content-type', b'text/plain')],
                })
                await send({
                    'type': 'http.response.body',
                    'body': f"UVICORN_LOADED:{uvicorn_loaded}".encode(),
                })
        """
        app_path = isolated_env.home / "app_sovereignty.py"
        app_path.write_text(textwrap.dedent(app_code))

        # We start with --rsgi
        proc, port, stdout_p, stderr_p, socket_dir, debug_log = run_velo_e2e(app_path)
        try:
            time.sleep(5)
            url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read().decode()

            # PROSECUTOR: If UVICORN_LOADED is True, Architectural Sovereignty is violated!
            assert "UVICORN_LOADED:False" in body, (
                f"SOVEREIGNTY VIOLATION: uvicorn pre-loaded in RSGI mode! Response: {body}"
            )
            print(f"Verified Native Sovereignty: {body}")

        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            import shutil

            shutil.rmtree(socket_dir, ignore_errors=True)

    @pytest.mark.tier1
    def test_websocket_501_unsupported(self, isolated_env, run_velo_e2e):
        """[RFC-0019] Verify C04: WebSocket handshake MUST return 501 Not Implemented."""
        app_code = """
        async def app(scope, receive, send):
            pass # Should not be reached
        """
        app_path = isolated_env.home / "app_ws.py"
        app_path.write_text(textwrap.dedent(app_code))

        proc, port, stdout_p, stderr_p, socket_dir, debug_log = run_velo_e2e(app_path)
        try:
            time.sleep(5)
            # Perform a manual HTTP request with WebSocket headers
            url = f"http://127.0.0.1:{port}/ws"
            req = urllib.request.Request(url)
            req.add_header("Upgrade", "websocket")
            req.add_header("Connection", "Upgrade")
            req.add_header("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZQ==")
            req.add_header("Sec-WebSocket-Version", "13")

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = resp.status
            except urllib.error.HTTPError as e:
                status = e.code

            try:
                assert status == 501, f"Expected 501 for WebSocket, got {status}"
            except AssertionError as e:
                raise e
            print(f"Verified C04: WebSocket returned {status}")

        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            import shutil

            shutil.rmtree(socket_dir, ignore_errors=True)

    @pytest.mark.tier1
    def test_signal_zombie_cleanup(self, isolated_env, run_velo_e2e):
        """[RFC-0019] Verify C06: Signal/Zombie cleanup - Host shutdown MUST reap all workers."""
        app_code = """
        import os
        import time
        import signal
        
        async def app(scope, receive, send):
            if scope['type'] == 'http':
                await send({
                    'type': 'http.response.start',
                    'status': 200,
                    'headers': [(b'content-type', b'text/plain')],
                })
                await send({
                    'type': 'http.response.body',
                    'body': b"OK",
                })
        """
        app_path = isolated_env.home / "app_cleanup.py"
        app_path.write_text(textwrap.dedent(app_code))

        # Start with 2 workers
        proc, port, stdout_p, stderr_p, socket_dir, debug_log = run_velo_e2e(app_path, extra_args=["--workers", "2"])
        try:
            time.sleep(5)
            # Verify it's up
            url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(url, timeout=10) as resp:
                assert resp.read() == b"OK"

            # Find worker PIDs
            import psutil

            parent = psutil.Process(proc.pid)
            # The structure is Host (Rust) -> Python (Zygote) -> Workers
            # But in RSGI mode with --rsgi, it might be different?
            # Actually with --rsgi, it's Host (Rust) -> Zygote -> Workers

            # Re-read debug log to find worker PIDs if possible, or use psutil
            worker_info = []
            for c in parent.children(recursive=True):
                try:
                    worker_info.append(
                        {"pid": c.pid, "name": c.name(), "cmdline": c.cmdline(), "create_time": c.create_time()}
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            print(f"Detected Process Tree: {worker_info}")
            target_pids = {w["pid"]: w["create_time"] for w in worker_info}
            worker_pids = [w["pid"] for w in worker_info]
            assert len(worker_pids) >= 3, (
                f"Expected at least 3 child processes (Zygote + 2 workers), found {len(worker_pids)}"
            )

            # Shut down Velo gracefully (SIGTERM to Host)
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                print("WARNING: Host failed to exit gracefully, forcing kill.")
                proc.kill()
                proc.wait()

            # Wait for all detected children to die
            time.sleep(6)

            # PROSECUTOR: Check if any worker PIDs still exist AND are the SAME processes
            failed = False
            survivors = []
            for pid, ct in target_pids.items():
                if psutil.pid_exists(pid):
                    try:
                        p = psutil.Process(pid)
                        if p.create_time() == ct and p.status() != psutil.STATUS_ZOMBIE:
                            survivors.append(
                                {
                                    "pid": pid,
                                    "status": p.status(),
                                    "ppid": p.ppid(),
                                    "name": p.name(),
                                    "cmdline": p.cmdline(),
                                    "create_time": p.create_time(),
                                }
                            )
                            failed = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                else:
                    # PID doesn't exist anymore, which is good
                    pass

            if failed:
                print(f"FAILED: Survivors detected: {survivors}")

                # ADVERSARIAL PROSECUTION: Can the test itself kill them?
                for s in survivors:
                    pid = s["pid"]
                    try:
                        print(f"Adversarial Prosecution: Attempting SIGKILL to {pid}...")
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(1)
                        p = psutil.Process(pid)
                        if p.is_running():
                            print(f"WARNING: PID {pid} survived adversarial SIGKILL!")
                        else:
                            print(f"INFO: PID {pid} died after adversarial SIGKILL.")
                    except Exception as e:
                        print(f"Adversarial Prosecution Error for {pid}: {e}")

                if stdout_p.exists():
                    with open(stdout_p) as f:
                        print(f"--- Velo Stdout ---\n{f.read()}\n------------------")
                if stderr_p.exists():
                    with open(stderr_p) as f:
                        print(f"--- Velo Stderr ---\n{f.read()}\n------------------")
                if debug_log.exists():
                    with open(debug_log) as f:
                        print(f"--- Zygote Worker Log ---\n{f.read()}\n------------------")
                assert False, f"ZOMBIE PERSISTENCE (C06): Workers {survivors} still alive after Host shutdown!"

            print("Verified C06: All workers reaped successfully.")

        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()
            import shutil

            shutil.rmtree(socket_dir, ignore_errors=True)
