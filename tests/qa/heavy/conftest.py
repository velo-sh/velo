import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

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
        T_MEDIUM,
        T_SHORT,
        VeloTestEnv,
        IS_LINUX,
        IS_MACOS,
        skip_unless_linux,
    )
except ImportError:
    sys.path.append(str(qa_path))
    import conftest_utils
    from conftest_utils import (
        T_MEDIUM,
        T_SHORT,
        VeloTestEnv,
        IS_LINUX,
        IS_MACOS,
        skip_unless_linux,
    )

# Common skip markers for Memory Gravity tests
skip_on_macos_security = pytest.mark.skipif(
    IS_MACOS, reason="macOS has no kernel-level sealing protection"
)
skip_on_macos_numa = pytest.mark.skipif(IS_MACOS, reason="macOS is single-NUMA-node")
skip_on_macos_hugepages = pytest.mark.skipif(IS_MACOS, reason="macOS has no HugePages support")
skip_on_macos_pid_namespace = pytest.mark.skipif(IS_MACOS, reason="macOS has no PID namespace support")

# =============================================================================
# VELO SERVE FIXTURE (Migrated from Phase 6.1.1)
# =============================================================================

class VeloServeProcess:
    """Wrapper for velo serve process with worker management."""

    def __init__(self, proc: subprocess.Popen, port: int, socket_path: str = None, forensic_secret: str = None):
        self.proc = proc
        self.port = port
        self.pid = proc.pid
        self.zygote_pid = None
        self.socket_path = socket_path
        self.forensic_secret = forensic_secret
        self._worker_pids: list[int] = []

    def is_running(self) -> bool:
        """Check if the main process is still running."""
        return self.proc.poll() is None

    def wait_ready(self, timeout: float = None) -> None:
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
                                self.zygote_pid = child.pid
                                return
                        else:
                            self.zygote_pid = child.pid
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

    def stop(self, timeout: float = None) -> None:
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

    def __init__(self, test_env, velo_binary: str):
        self.test_env = test_env
        self.velo_binary = velo_binary
        self.processes: list[VeloServeProcess] = []

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
        socket_dir = Path("/tmp") / f"velo-test-{h}"
        socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        socket_path = socket_dir / "z.s"
        
        env["VELO_ZYGOTE_PATH"] = str(Path(__file__).parents[3] / "velo_zygote/main.py")
        env["VELO_SOCKET_DIR"] = str(socket_dir)
        env["VELO_ZYGOTE_SOCKET"] = str(socket_path)
        
        import uuid
        env["VELO_ZYGOTE_AUTH"] = str(uuid.uuid4())

        proc = subprocess.Popen(cmd, cwd=self.test_env.root, env=env, stdout=None, stderr=None)
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
def velo_serve_fixture(velo_test_env, velo_binary: str):
    """Fixture for starting velo serve processes."""
    app_file = velo_test_env.root / "main.py"
    app_file.write_text(SAMPLE_APP_CODE)
    pyproject_file = velo_test_env.root / "pyproject.toml"
    pyproject_file.write_text('[project]\ndependencies = ["fastapi"]')

    factory = VeloServeFactory(velo_test_env, velo_binary)
    yield factory
    factory.cleanup()

@pytest.fixture
def shm_test_env(isolated_env: VeloTestEnv):
    """
    Extended environment for SHM-specific tests.
    """
    test_data_dir = isolated_env.path / "test_data"
    test_data_dir.mkdir(exist_ok=True)
    yield isolated_env

SAMPLE_APP_CODE = '''
from fastapi import FastAPI
import os

app = FastAPI()

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
'''
