import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

# =============================================================================
# CI FLAKY AUTO-SKIP FOR HEAVY TESTS (Option A: Skip heavy tests in CI)
# =============================================================================


def pytest_collection_modifyitems(config, items):
    """Auto-skip heavy tests in CI environment - these are too resource-intensive."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("VELO_FORCE_HEAVY") == "1":
        return  # Only apply in CI unless forced

    skip_in_ci = pytest.mark.skip(reason="Heavy tests: skipped in CI (resource constraints)")

    for item in items:
        # All tests in this directory get the skip marker in CI
        item.add_marker(skip_in_ci)


# Add project root and python directory to sys.path
# tests/qa/heavy/conftest.py
# .parent = heavy
# .parent.parent = qa
# .parent.parent.parent = tests
# .parent.parent.parent.parent = root (parents[3])

root = Path(__file__).parents[3]
python_path = root / "python"
qa_path = root / "tests" / "qa"
utils_path = qa_path / "utils"

if str(python_path) not in sys.path:
    sys.path.insert(0, str(python_path))
if str(qa_path) not in sys.path:
    sys.path.insert(0, str(qa_path))
if str(utils_path) not in sys.path:
    sys.path.insert(0, str(utils_path))

# Ensure conftest_utils is available
try:
    import conftest_utils
    from conftest_utils import (
        IS_LINUX,
        IS_MACOS,
        T_MEDIUM,
        T_SHORT,
        VeloTestEnv,
        skip_unless_linux,
    )
except ImportError:
    sys.path.append(str(qa_path))
    from conftest_utils import (
        IS_MACOS,
        T_MEDIUM,
        T_SHORT,
        VeloTestEnv,
    )

# Common skip markers for Memory Gravity tests
skip_on_macos_security = pytest.mark.skipif(IS_MACOS, reason="macOS has no kernel-level sealing protection")
skip_on_macos_numa = pytest.mark.skipif(IS_MACOS, reason="macOS is single-NUMA-node")
skip_on_macos_hugepages = pytest.mark.skipif(IS_MACOS, reason="macOS has no HugePages support")
skip_on_macos_pid_namespace = pytest.mark.skipif(IS_MACOS, reason="macOS has no PID namespace support")

# =============================================================================
# VELO SERVE FIXTURE (Migrated from Phase 6.1.1)
# =============================================================================


class VeloServeProcess:
    """Wrapper for velo serve process with worker management."""

    def __init__(
        self, proc: subprocess.Popen[str], port: int, socket_path: str | None = None, forensic_secret: str | None = None
    ):
        self.proc = proc
        self.port = port
        self.pid = proc.pid
        self.zygote_pid: int | None = None
        self.socket_path = socket_path
        self.forensic_secret = forensic_secret
        self._worker_pids: list[int] = []

    def is_running(self) -> bool:
        """Check if the main process is still running."""
        return self.proc.poll() is None

    def get_socket_path(self) -> str | None:
        """Return the Zygote socket path."""
        return self.socket_path

    def wait_ready(self, timeout: float | None = None) -> None:
        """Wait for server to be ready to accept requests."""
        if timeout is None:
            timeout = T_MEDIUM + T_SHORT
        import requests

        start = time.time()
        while time.time() - start < timeout:
            if not self.is_running():
                exit_code = self.proc.returncode
                time.sleep(0.2)
                raise RuntimeError(f"Server process died (exit code: {exit_code})")

            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                if r.status_code == 200:
                    self._detect_zygote_pid()
                    return
            except Exception:
                pass
            time.sleep(0.01)

        self.proc.terminate()
        try:
            self.proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        raise TimeoutError(f"Server not ready after {timeout}s")

    def _detect_zygote_pid(self) -> None:
        """Find the Zygote process PID by checking children of Velo supervisor."""
        if self.zygote_pid:
            return

        try:
            supervisor = psutil.Process(self.pid)
            for child in supervisor.children(recursive=True):
                try:
                    cmdline = child.cmdline()
                    cmdline_str = " ".join(cmdline).lower()
                    if "velo_zygote/main.py" in cmdline_str:
                        if self.socket_path:
                            if any(self.socket_path in arg for arg in cmdline):
                                self.zygote_pid = int(child.pid)
                                return
                        else:
                            self.zygote_pid = int(child.pid)
                            return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def get_worker_pids(self) -> list[int]:
        """Get list of worker PIDs."""
        for _ in range(10):
            if not self.zygote_pid:
                self._detect_zygote_pid()

            workers = []
            if self.zygote_pid:
                try:
                    zygote_proc = psutil.Process(self.zygote_pid)
                    workers.extend([child.pid for child in zygote_proc.children(recursive=True)])
                except psutil.NoSuchProcess:
                    self.zygote_pid = None

            try:
                supervisor = psutil.Process(self.pid)
                for child in supervisor.children(recursive=True):
                    try:
                        cmdline = " ".join(child.cmdline()).lower()
                        if any(x in cmdline for x in ["python", "granian", "uvicorn", "worker-native"]):
                            if "velo_zygote/main.py" not in cmdline:
                                if child.pid not in workers:
                                    workers.append(child.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except psutil.NoSuchProcess:
                pass

            if workers:
                return workers
            time.sleep(0.1)

        return []

    def stop(self, timeout: float | None = None) -> None:
        """Stop the server gracefully."""
        if timeout is None:
            timeout = T_SHORT
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


class VeloServeFactory:
    """Factory for creating VeloServeProcess instances."""

    def __init__(self, test_env: Any, velo_binary: str):
        self.test_env = test_env
        self.velo_binary = velo_binary
        self.processes: list[VeloServeProcess] = []

    @property
    def tmp_path(self) -> Path:
        """Return the test environment root path for creating test files."""
        return Path(self.test_env.root)

    def start(
        self,
        app: str,
        workers: int = 1,
        zygote: bool = True,
        port: int | None = None,
        rsgi: bool = False,
        extra_args: list[str] | None = None,
    ) -> VeloServeProcess:
        """Start a velo serve process."""
        if port is None:
            import socket

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port = s.getsockname()[1]

        cmd = [self.velo_binary, "serve", app, "--workers", str(workers), "--port", str(port)]
        if not zygote:
            cmd.append("--no-zygote")
        if rsgi:
            cmd.append("--rsgi")
        if extra_args:
            cmd.extend(extra_args)

        env = self.test_env.env.copy()

        import hashlib

        h = hashlib.md5(str(self.test_env.root).encode()).hexdigest()[:8]
        # FIX: Append random suffix to prevent race conditions
        import uuid

        rand_suffix = str(uuid.uuid4())[:8]
        socket_dir = Path("/tmp") / f"velo-test-{h}-{rand_suffix}"
        socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        socket_path = socket_dir / "z.s"

        env["VELO_ZYGOTE_PATH"] = str(Path(__file__).parents[3] / "velo_zygote/main.py")
        env["VELO_SOCKET_DIR"] = str(socket_dir)
        env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

        import uuid

        env["VELO_ZYGOTE_AUTH"] = str(uuid.uuid4())

        proc = subprocess.Popen(cmd, cwd=self.test_env.root, env=env, stdout=None, stderr=None, text=True)
        wrapper = VeloServeProcess(proc, port, str(socket_path), env["VELO_ZYGOTE_AUTH"])
        self.processes.append(wrapper)
        return wrapper

    def cleanup(self) -> None:
        for p in self.processes:
            try:
                p.stop()
            except Exception:
                pass


@pytest.fixture
def velo_serve_fixture(velo_test_env: Any, velo_binary: str) -> Any:
    """Fixture for starting velo serve processes."""
    app_file = velo_test_env.root / "main.py"
    app_file.write_text(SAMPLE_APP_CODE)
    pyproject_file = velo_test_env.root / "pyproject.toml"
    pyproject_file.write_text('[project]\ndependencies = ["fastapi"]')

    factory = VeloServeFactory(velo_test_env, velo_binary)
    yield factory
    factory.cleanup()


@pytest.fixture
def shm_test_env(isolated_env: VeloTestEnv) -> Any:
    """
    Extended environment for SHM-specific tests.
    """
    test_data_dir = isolated_env.path / "test_data"
    test_data_dir.mkdir(exist_ok=True)
    yield isolated_env


SAMPLE_APP_CODE = """
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import os
import asyncio
import time

app = FastAPI()

# Global counter for concurrency testing
active_requests = 0
max_concurrent_seen = 0

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"healthy": True}

@app.get("/ping")
async def ping():
    return {"ping": "pong"}

@app.get("/whoami")
async def whoami():
    return {"pid": os.getpid(), "ppid": os.getppid()}

@app.get("/headers")
async def get_headers(request: Request):
    return dict(request.headers)

@app.get("/scope")
async def get_scope(request: Request):
    # Filter scope for JSON serialization
    safe_scope = {}
    for k, v in request.scope.items():
        if isinstance(v, (str, int, float, bool, list, dict)) or v is None:
            safe_scope[k] = v
        elif isinstance(v, bytes):
            safe_scope[k] = v.decode("latin1")
        elif k == "client" or k == "server":
            safe_scope[k] = list(v) if v else None
    return safe_scope

@app.get("/client-ip")
async def get_client_ip(request: Request):
    return {
        "client_host": request.client.host if request.client else None,
        "client_port": request.client.port if request.client else None,
        "xff": request.headers.get("x-forwarded-for"),
    }

@app.post("/echo")
async def echo(request: Request):
    data = await request.json()
    return {
        "received_message": data.get("message"),
        "received_number": data.get("number"),
        "worker_pid": os.getpid(),
    }

@app.get("/concurrent")
async def concurrent_test():
    global active_requests, max_concurrent_seen
    active_requests += 1
    max_concurrent_seen = max(max_concurrent_seen, active_requests)
    await asyncio.sleep(0.1)
    res = {"max_concurrent_seen": max_concurrent_seen}
    active_requests -= 1
    return res

@app.get("/large")
async def large_response(size_kb: int = 1):
    data = "V" * (size_kb * 1024)
    return {"size_kb": size_kb, "data": data}

@app.get("/slow")
async def slow_response(seconds: float = 1.0):
    await asyncio.sleep(seconds)
    return {"slept": seconds}

@app.get("/error/{code}")
async def error_response(code: int):
    status_map = {
        404: "Not Found",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }
    return JSONResponse(
        status_code=code,
        content={"error": status_map.get(code, "Unknown Error")}
    )
"""
