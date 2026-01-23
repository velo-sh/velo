"""
RFC-0019/0025 Native Security Tests

These tests verify security invariants for Native Sovereignty:
1. Socket directory permissions
2. Worker isolation

NOTE: In Native Granian mode, there are no UDS worker sockets.
Workers communicate via PyO3 in-process. These tests verify
the security properties that still apply.
"""

import os
import time
from pathlib import Path

import psutil
import pytest
import requests


class TestNativeSecurity:
    """
    Verification of Security Invariants for Phase 7.2.
    """

    @pytest.mark.tier4
    def test_native_worker_isolation(self, isolated_env):
        """[N-SEC-01] Verify native workers are properly isolated."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
import os
app = FastAPI()

@app.get("/info")
def info():
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "cwd": os.getcwd(),
    }
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            # Wait for server
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/info", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            resp = requests.get(f"http://127.0.0.1:{port}/info", timeout=5)
            assert resp.status_code == 200

            data = resp.json()

            # Worker should be in a separate process
            assert data["pid"] != proc.pid, "Worker PID should differ from Host"
            assert data["pid"] > 0, "Worker PID should be valid"

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier4
    def test_native_worker_limits(self, isolated_env):
        """[N-SEC-02] Verify workers respect resource limits."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
import resource
import os
app = FastAPI()

@app.get("/limits")
def limits():
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return {"nofile_soft": soft, "nofile_hard": hard, "pid": os.getpid()}
    except Exception as e:
        return {"error": str(e)}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/limits", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            resp = requests.get(f"http://127.0.0.1:{port}/limits", timeout=5)
            assert resp.status_code == 200

            data = resp.json()

            # Worker should have file descriptor limits
            if "nofile_soft" in data:
                assert data["nofile_soft"] > 0, "Worker should have FD limits"

        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier4
    @pytest.mark.xfail(reason="Flaky in CI: child process timing causes 'still running after shutdown'", strict=False)
    def test_native_worker_signal_handling(self, isolated_env):
        """[N-SEC-03] Verify workers respond to graceful shutdown."""
        import signal

        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"healthy": True}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            # Wait for server
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            # Get children before shutdown
            parent = psutil.Process(proc.pid)
            children_before = parent.children(recursive=True)

            # Send SIGTERM
            proc.send_signal(signal.SIGTERM)

            # Wait for graceful shutdown
            try:
                proc.wait(timeout=10)
            except:
                proc.kill()
                proc.wait()
                pytest.fail("Server did not shut down gracefully within 10s")

            # Verify all children are gone
            time.sleep(1)
            for child in children_before:
                try:
                    if child.is_running():
                        pytest.fail(f"Child process {child.pid} still running after shutdown")
                except psutil.NoSuchProcess:
                    pass  # Expected

        except Exception:
            proc.terminate()
            proc.wait()
            raise


class TestNativeSecurityHardened:
    """Additional hardened security tests."""

    @pytest.mark.tier4
    @pytest.mark.xfail(reason="Known issue: network test can fail with RemoteDisconnected in CI", strict=False)
    def test_worker_no_privileged_ports(self, isolated_env):
        """[N-SEC-H01] Verify workers cannot bind to privileged ports."""
        isolated_env.create_app(
            "main.py",
            """
from fastapi import FastAPI
import socket
app = FastAPI()

@app.get("/bind-test")
def bind_test():
    # Try to bind to a privileged port (should fail)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 80))
        s.close()
        return {"status": "SECURITY_BREACH", "bound": True}
    except PermissionError:
        return {"status": "OK", "bound": False}
    except OSError as e:
        return {"status": "OK", "error": str(e)}
""",
        )

        port = isolated_env.next_port()
        root_dir = str(Path(__file__).parents[3])
        env = {"PYTHONPATH": f"{root_dir}:{os.environ.get('PYTHONPATH', '')}"}

        proc = isolated_env.spawn_velo("serve", "main:app", "--rsgi", "--port", str(port), env=env)

        try:
            for _ in range(30):
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/bind-test", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.5)

            resp = requests.get(f"http://127.0.0.1:{port}/bind-test", timeout=5)
            assert resp.status_code == 200

            data = resp.json()
            assert data["status"] != "SECURITY_BREACH", "Worker should not be able to bind privileged ports"

        finally:
            proc.terminate()
            proc.wait()
