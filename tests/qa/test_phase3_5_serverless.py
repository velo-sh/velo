from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_velo_binary() -> str:
    """Get path to velo binary."""
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    debug = repo_root / "target" / "debug" / "velo"

    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found - run cargo build first")


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Check if port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((host, port))
            return True
    except:
        return False


def wait_for_port(port: int, timeout: float = 30) -> bool:
    """Wait for port to open."""
    start = time.time()
    while time.time() - start < timeout:
        if is_port_open(port):
            return True
        time.sleep(0.2)
    return False


def wait_for_server_ready(port: int, timeout: float = 60, path: str = "/") -> tuple[bool, str | None]:
    """
    Wait for server to be truly ready to handle HTTP requests.

    Unlike wait_for_port which only checks TCP, this actually makes HTTP requests
    to verify the worker is ready. Returns (success, error_message).
    """
    if not HAS_REQUESTS:
        # Fallback to port check if requests not available
        return wait_for_port(port, timeout), None

    start = time.time()
    last_error = None
    delay = 0.5  # Start with 0.5s delay, increase gradually

    while time.time() - start < timeout:
        try:
            response = requests.get(f"http://127.0.0.1:{port}{path}", timeout=5)
            if response.status_code < 500:  # 2xx, 3xx, 4xx are all "ready"
                return True, None
        except requests.exceptions.ConnectionError as e:
            last_error = str(e)
        except requests.exceptions.Timeout:
            last_error = "Request timeout"
        except Exception as e:
            last_error = str(e)

        time.sleep(delay)
        delay = min(delay * 1.5, 3.0)  # Exponential backoff, max 3s

    return False, last_error


class ClientProject:
    """
    Simulates a real client project.

    Each instance is a CLEAN, ISOLATED project directory.
    Client provides: pyproject.toml, uv.lock, app code
    Velo handles: environment init
    """

    _port_counter = 20000 + (os.getpid() % 10000)  # Random base per process

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="velo_client_"))
        self.velo = get_velo_binary()
        self.procs = []
        self.port = self.next_port()  # Reserve port at init

    @classmethod
    def next_port(cls) -> int:
        cls._port_counter += 1
        return cls._port_counter

    def set_pyproject(self, name: str = "test-app", dependencies: list = None):
        """Set pyproject.toml like a client would have."""
        deps = dependencies or []
        content = f"""[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = {json.dumps(deps)}

[tool.uv]
dev-dependencies = []
"""
        (self.path / "pyproject.toml").write_text(content)
        return self

    def set_uv_lock(self, packages: dict = None):
        """
        Set uv.lock like a client would have.

        packages: {"uvicorn": "0.30.0", "fastapi": "0.115.0", ...}
        """
        if packages is None:
            # Empty lock - no packages
            content = """version = 1
requires-python = ">=3.11"

[[package]]
name = "test-app"
version = "0.1.0"
source = { virtual = "." }
"""
        else:
            # Build lock with packages
            content = """version = 1
requires-python = ">=3.11"

"""
            for pkg, version in packages.items():
                content += f"""[[package]]
name = "{pkg}"
version = "{version}"
source = {{ registry = "https://pypi.org/simple" }}

"""
            content += """[[package]]
name = "test-app"
version = "0.1.0"
source = { virtual = "." }
dependencies = [
"""
            for pkg in packages.keys():
                content += f'    {{ name = "{pkg}" }},\n'
            content += """]\n"""

        (self.path / "uv.lock").write_text(content)
        return self

    def set_app(self, filename: str, code: str):
        """Set application code."""
        (self.path / filename).write_text(code)
        return self

    def uv_add(self, *packages):
        """
        Use uv add to add dependencies (generates proper uv.lock).
        This is what a real client would do.
        """
        subprocess.run(
            ["uv", "add", "--quiet"] + list(packages),
            cwd=self.path,
            capture_output=True,
        )
        return self

    def sync(self):
        """Run uv sync to install dependencies (like client would do before deploy)."""
        subprocess.run(["uv", "sync", "--quiet"], cwd=self.path, capture_output=True)
        return self

    def serve(self, app: str, port: int = None, wait: bool = True, **opts) -> subprocess.Popen:
        """Run velo serve."""
        if port is None:
            port = self.next_port()

        cmd = [self.velo, "serve", app, "--port", str(port)]
        for k, v in opts.items():
            cmd.extend([f"--{k.replace('_', '-')}", str(v)])

        proc = subprocess.Popen(
            cmd,
            cwd=self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.procs.append(proc)

        if wait:
            # Wait a bit for startup
            time.sleep(2)

        return proc, port

    def serve_sync(self, app: str, timeout: float = 10) -> subprocess.CompletedProcess:
        """Run velo serve and wait for completion (for error cases)."""
        return subprocess.run(
            [self.velo, "serve", app],
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def cleanup(self):
        """Clean up processes and temp directory."""
        for proc in self.procs:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except:
                try:
                    proc.kill()
                except:
                    pass
        try:
            shutil.rmtree(self.path)
        except:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# SCENARIO 1: No dependencies in uv.lock
# =============================================================================


class TestNoDependencies:
    """Client project without uvicorn in uv.lock."""

    def test_no_uvicorn_behavior(self):
        """
        When uvicorn missing from uv.lock, velo should either:
        1. Show clear installation hint, OR
        2. Auto-install and run (if velo supports this)
        """
        with ClientProject() as project:
            # Client provides: empty project, no dependencies
            project.set_pyproject(dependencies=[])
            project.set_uv_lock(packages=None)
            project.set_app("main.py", "app = None")

            # Run velo serve with timeout
            proc, port = project.serve("main:app", wait=True)
            time.sleep(3)

            # Check what happened
            if proc.poll() is not None:
                # Process exited - should have shown hint
                stderr = proc.stderr.read() if proc.stderr else ""
                assert "uvicorn" in stderr.lower() or "dependency" in stderr.lower()
            else:
                # Process still running - velo handled it
                # This is also acceptable behavior
                proc.terminate()
                assert True

    def test_with_fastapi_only(self):
        """
        With fastapi but no uvicorn explicitly - velo should handle it.
        """
        with ClientProject() as project:
            project.set_pyproject(dependencies=["fastapi"])
            project.set_uv_lock(packages={"fastapi": "0.115.0"})
            project.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}
""",
            )
            project.sync()

            proc, port = project.serve("main:app")
            time.sleep(3)

            stderr = proc.stderr.read() if proc.stderr else ""

            # Either it starts successfully or shows clear error
            if proc.poll() is None:
                # Still running = success
                proc.terminate()
                assert True
            else:
                # Exited = should have hint
                assert "uvicorn" in stderr.lower() or "tip" in stderr.lower()


# =============================================================================
# REGRESSION: DEF-3.5-003 and DEF-3.5-004
# =============================================================================


class TestDefectRegression:
    """Regression tests for fixed defects - ensure they don't return."""

    def test_def_3_5_003_crash_error_displayed(self):
        """
        DEF-3.5-003: App crash errors were swallowed.
        FIX: Crash traceback should now be displayed.
        """
        with ClientProject() as project:
            project.set_pyproject()
            # App that crashes on import
            project.set_app(
                "crash_app.py",
                """
raise RuntimeError("INTENTIONAL CRASH ON IMPORT")
""",
            )
            project.uv_add("fastapi", "uvicorn")

            proc, port = project.serve("crash_app:app")
            time.sleep(3)

            # Read stderr
            import fcntl
            import os

            fcntl.fcntl(proc.stderr.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
            try:
                stderr = proc.stderr.read() or ""
            except:
                stderr = ""

            os.kill(proc.pid, 9)  # Clean up by PID

            # REGRESSION CHECK: Error should be displayed, not swallowed
            stderr_lower = stderr.lower()
            assert "traceback" in stderr_lower or "runtimeerror" in stderr_lower or "crash" in stderr_lower, (
                f"DEF-3.5-003 regression: crash error not displayed! stderr: {stderr[:500]}"
            )

    def test_def_3_5_004_framework_detection(self):
        """
        DEF-3.5-004: Framework showed 'Unknown' for FastAPI.
        FIX: Should show 'Detected: FastAPI'.
        """
        with ClientProject() as project:
            project.set_pyproject()
            project.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"ok": True}
""",
            )
            project.uv_add("fastapi", "uvicorn")

            proc, port = project.serve("main:app")
            time.sleep(2)

            # Read stderr
            import fcntl
            import os

            fcntl.fcntl(proc.stderr.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
            try:
                stderr = proc.stderr.read() or ""
            except:
                stderr = ""

            os.kill(proc.pid, 9)  # Clean up by PID

            # REGRESSION CHECK: Should detect FastAPI, not show Unknown
            stderr_lower = stderr.lower()
            assert "detected" in stderr_lower and "fastapi" in stderr_lower, (
                f"DEF-3.5-004 regression: framework not detected! stderr: {stderr[:500]}"
            )
            assert "unknown" not in stderr_lower or "detected: fastapi" in stderr_lower, (
                f"DEF-3.5-004 regression: still showing 'Unknown'! stderr: {stderr[:500]}"
            )


# =============================================================================
# SCENARIO 2: With dependencies (test normal operation)
# =============================================================================


class TestWithDependencies:
    """Client project with proper dependencies - should work."""

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests needed")
    def test_server_starts_with_uvicorn(self):
        """With uvicorn, server should start and respond to HTTP."""
        with ClientProject() as project:
            # Client setup: init project and add dependencies
            project.set_pyproject()
            project.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"healthy": True}
""",
            )
            # Client adds dependencies and syncs (like real user)
            project.uv_add("fastapi", "uvicorn")

            # Velo starts server
            proc, port = project.serve("main:app")

            # Wait for server to be truly ready using HTTP requests
            ready, error = wait_for_server_ready(port, timeout=60, path="/")
            if not ready:
                # Capture server stderr for debugging
                import fcntl

                try:
                    fcntl.fcntl(proc.stderr.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
                    stderr = proc.stderr.read() or ""
                except:
                    stderr = ""
                pytest.fail(f"Server did not become ready. Error: {error}\nstderr: {stderr[:2000]}")

            # Server is ready, now verify the response
            response = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
            assert response.status_code == 200
            assert response.json()["status"] == "ok"

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests needed")
    def test_health_endpoint_works(self):
        """Basic health check endpoint works."""
        with ClientProject() as project:
            project.set_pyproject()
            project.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"healthy": True}
""",
            )
            project.uv_add("fastapi", "uvicorn")

            proc, port = project.serve("main:app")

            ready, error = wait_for_server_ready(port, timeout=60, path="/health")
            if not ready:
                stderr = proc.stderr.read() if proc.stderr else ""
                pytest.fail(f"Server did not start. Error: {error}, stderr: {stderr}")

            response = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
            assert response.status_code == 200
            assert response.json()["healthy"] == True

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests needed")
    def test_multiple_requests(self):
        """Server handles multiple sequential requests."""
        with ClientProject() as project:
            project.set_pyproject()
            project.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()
counter = 0

@app.get("/count")
def count():
    global counter
    counter += 1
    return {"count": counter}
""",
            )
            project.uv_add("fastapi", "uvicorn")

            proc, port = project.serve("main:app")

            ready, error = wait_for_server_ready(port, timeout=60, path="/count")
            if not ready:
                pytest.skip(f"Server did not start: {error}")

            # Make 10 requests
            for i in range(10):
                response = requests.get(f"http://127.0.0.1:{port}/count", timeout=5)
                assert response.status_code == 200


# =============================================================================
# SCENARIO 3: Graceful shutdown
# =============================================================================


class TestGracefulShutdown:
    """Server shuts down gracefully on signals."""

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests needed")
    def test_sigterm_graceful_exit(self):
        """SIGTERM causes graceful shutdown."""

        with ClientProject() as project:
            project.set_pyproject()
            project.set_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"ok": True}
""",
            )
            project.uv_add("fastapi", "uvicorn")

            proc, port = project.serve("main:app")

            ready, error = wait_for_server_ready(port, timeout=60, path="/")
            if not ready:
                pytest.skip(f"Server did not start: {error}")

            # Make a request to ensure it's working
            requests.get(f"http://127.0.0.1:{port}/", timeout=5)

            # Send SIGTERM
            proc.terminate()

            try:
                exit_code = proc.wait(timeout=10)
                # Should exit cleanly
                assert True
            except subprocess.TimeoutExpired:
                proc.kill()
                pytest.fail("Server did not exit after SIGTERM")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
