# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/conftest.py

"""
Shared fixtures for RFC-0011 Zygote Worker Integration tests.

Following QA SOP v2.2:
- Test Environment Isolation
- Explicit Assertions
- Reproducible Tests
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import psutil
import pytest

# Import CI-aware timeout constants from parent conftest
sys.path.append(str(Path(__file__).parent.parent))
from conftest import T_SHORT, T_MEDIUM, T_LONG, get_timeout_multiplier



class VeloServeProcess:
    """Wrapper for velo serve process with worker management."""

    def __init__(self, proc: subprocess.Popen, port: int, socket_path: str = None):
        self.proc = proc
        self.port = port
        self.pid = proc.pid
        self.zygote_pid = None
        self.socket_path = socket_path
        self._worker_pids: List[int] = []

    def is_running(self) -> bool:
        """Check if the main process is still running."""
        return self.proc.poll() is None

    def wait_ready(self, timeout: float = None) -> None:
        """Wait for server to be ready to accept requests."""
        if timeout is None:
            timeout = T_MEDIUM + T_SHORT  # ~15s base -> ~90s scaled in CI
        import requests

        start = time.time()
        while time.time() - start < timeout:
            if not self.is_running():
                raise RuntimeError("Server process died")
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                if r.status_code == 200:
                    self._detect_zygote_pid()
                    return
            except Exception:
                pass
            time.sleep(0.1)
        
        # On timeout, try to read what happened
        print("Timeout reached.")
        self.proc.terminate()
        raise TimeoutError(f"Server not ready after {timeout}s")

    def wait_worker_ready(self, timeout: float = None) -> None:
        """Wait for a worker to be ready after restart."""
        if timeout is None:
            timeout = T_SHORT
        import requests

        start = time.time()
        while time.time() - start < timeout:
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.1)

    def _detect_zygote_pid(self) -> None:
        """Find the Zygote process PID by checking children of Velo supervisor."""
        if self.zygote_pid:
            return
            
        try:
            supervisor = psutil.Process(self.pid)
            # Search children recursively. The Zygote is usually a direct child.
            for child in supervisor.children(recursive=True):
                try:
                    cmdline = child.cmdline()
                    cmdline_str = " ".join(cmdline).lower()
                    if "velo_zygote/main.py" in cmdline_str:
                        # If we have a specific socket path, match it
                        if self.socket_path:
                            if any(self.socket_path in arg for arg in cmdline):
                                self.zygote_pid = child.pid
                                return
                        else:
                            # Fallback to any Zygote child
                            self.zygote_pid = child.pid
                            return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def get_worker_pids(self) -> List[int]:
        """Get list of worker PIDs.
        
        Workers are forked from the Zygote, so they are children of the Zygote PID.
        Includes a short retry loop to account for fork latency.
        """
        for _ in range(10):
            if not self.zygote_pid:
                self._detect_zygote_pid()
            
            if self.zygote_pid:
                try:
                    zygote_proc = psutil.Process(self.zygote_pid)
                    workers = [child.pid for child in zygote_proc.children(recursive=False)]
                    if workers:
                        return workers
                except psutil.NoSuchProcess:
                    self.zygote_pid = None
            
            time.sleep(0.2)
        
        return []

    def get_metrics(self) -> dict:
        """Get server metrics (placeholder for future implementation)."""
        return {"worker_requests": {}}

    def get_socket_path(self) -> Optional[str]:
        """Find the Zygote socket path by inspecting Zygote command line."""
        if not self.zygote_pid:
            self._detect_zygote_pid()
        
        if self.zygote_pid:
            try:
                proc = psutil.Process(self.zygote_pid)
                cmdline = proc.cmdline()
                for i, arg in enumerate(cmdline):
                    if arg == "--socket" and i + 1 < len(cmdline):
                        return cmdline[i + 1]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

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
        self.tmp_path = test_env.root # Compatibility
        self.velo_binary = velo_binary
        self.processes: List[VeloServeProcess] = []

    def start(
        self,
        app: str,
        workers: int = 1,
        zygote: bool = True, # Default to True as per new Velo default
        port: Optional[int] = None,
        extra_args: Optional[List[str]] = None,
    ) -> VeloServeProcess:
        """Start a velo serve process."""
        if port is None:
            # Find a free port
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                port = s.getsockname()[1]

        cmd = [
            self.velo_binary,
            "serve",
            app,
            "--workers",
            str(workers),
            "--port",
            str(port),
        ]
        
        # In new version, Zygote is default. We only use --no-zygote to disable.
        if not zygote:
            cmd.append("--no-zygote")
        
        if extra_args:
            cmd.extend(extra_args)

        # RFC-0012: Use hermetic environment
        env = self.test_env.env.copy()
        
        # RFC-0011/0012: Ensure socket path does NOT exceed 104 chars (macOS limit)
        # We prioritize a short, stable path in /tmp for tests to avoid deep nesting issues.
        import hashlib
        h = hashlib.md5(str(self.tmp_path).encode()).hexdigest()[:8]
        socket_dir = Path("/tmp") / f"velo-test-{h}"
        socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        socket_path = socket_dir / "z.s"
        
        env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

        proc = subprocess.Popen(
            cmd,
            cwd=self.tmp_path, # Execute in test root
            env=env,
            # Use None to inherit from parent, so -s shows it
            stdout=None,
            stderr=None,
        )
        wrapper = VeloServeProcess(proc, port, str(socket_path))
        self.processes.append(wrapper)
        return wrapper

    def cleanup(self) -> None:
        """Stop all processes."""
        for p in self.processes:
            try:
                p.stop()
            except Exception:
                pass


def find_velo_binary() -> str:
    """Find the velo binary (release > debug > PATH)."""
    repo_root = Path(__file__).parent.parent.parent.parent

    # Check release build first
    release_bin = repo_root / "target" / "release" / "velo"
    if release_bin.exists():
        return str(release_bin)

    # Check debug build
    debug_bin = repo_root / "target" / "debug" / "velo"
    if debug_bin.exists():
        return str(debug_bin)

    # Fall back to PATH
    import shutil

    path_bin = shutil.which("velo")
    if path_bin:
        return path_bin

    pytest.skip("Velo binary not found. Run 'cargo build --release' first.")


@pytest.fixture(scope="session")
def velo_binary() -> str:
    """Session-scoped fixture for velo binary path."""
    return find_velo_binary()


@pytest.fixture
def velo_serve_fixture(velo_test_env, velo_binary: str):
    """Fixture for starting velo serve processes."""
    # Create sample app in root
    app_file = velo_test_env.root / "main.py"
    app_file.write_text(SAMPLE_APP_CODE)

    # Create pyproject.toml to enable framework detection (required for Zygote)
    pyproject_file = velo_test_env.root / "pyproject.toml"
    pyproject_file.write_text('[project]\ndependencies = ["fastapi"]')

    factory = VeloServeFactory(velo_test_env, velo_binary)
    yield factory
    factory.cleanup()





# Helper functions


def get_rss(pid: int) -> int:
    """Get Resident Set Size in bytes."""
    try:
        return psutil.Process(pid).memory_info().rss
    except psutil.NoSuchProcess:
        return 0


def get_pss(pid: int) -> int:
    """Get Proportional Set Size in bytes (Linux only)."""
    if sys.platform != "linux":
        return get_rss(pid)
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except FileNotFoundError:
        return get_rss(pid)
    return 0


def get_ppid(pid: int) -> int:
    """Get parent process ID."""
    try:
        return psutil.Process(pid).ppid()
    except psutil.NoSuchProcess:
        return 0


# Sample app code for testing
SAMPLE_APP_CODE = '''
"""Sample FastAPI app for RFC-0011 QA tests."""

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import os
import signal
import asyncio

app = FastAPI()

# Track concurrent requests for testing
_concurrent_counter = 0
_max_concurrent = 0


class EchoBody(BaseModel):
    message: str
    number: int = 0


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"healthy": True}


@app.get("/ping")
async def ping():
    return {"ping": "pong"}


@app.get("/slow")
async def slow(seconds: int = 1):
    await asyncio.sleep(seconds)
    return {"slept": seconds}


@app.get("/headers")
async def headers(request: Request):
    return dict(request.headers)


@app.get("/client-ip")
async def client_ip(request: Request):
    return {
        "client_host": request.client.host if request.client else None,
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
    }


@app.get("/whoami")
async def whoami():
    return {"pid": os.getpid(), "ppid": os.getppid()}


@app.get("/debug/signals")
async def debug_signals():
    handlers = {}
    for sig_name in ["SIGINT", "SIGTERM", "SIGCHLD"]:
        try:
            sig = getattr(signal, sig_name)
            handler = signal.getsignal(sig)
            if handler == signal.SIG_DFL:
                handlers[sig_name] = "SIG_DFL"
            elif handler == signal.SIG_IGN:
                handlers[sig_name] = "SIG_IGN"
            else:
                handlers[sig_name] = str(handler)
        except Exception as e:
            handlers[sig_name] = f"error: {e}"
    return handlers


# ============================================================================
# Additional endpoints for E2E demon-catching tests
# ============================================================================

@app.post("/echo")
async def echo_body(body: EchoBody):
    """Echo back POST body - tests request body handling through proxy."""
    return {
        "received_message": body.message,
        "received_number": body.number,
        "worker_pid": os.getpid(),
    }


@app.get("/error/{code}")
async def trigger_error(code: int):
    """Simulate error responses - tests error handling through proxy."""
    if code == 500:
        raise HTTPException(status_code=500, detail="Simulated server error")
    elif code == 404:
        raise HTTPException(status_code=404, detail="Simulated not found")
    elif code == 503:
        raise HTTPException(status_code=503, detail="Simulated service unavailable")
    else:
        raise HTTPException(status_code=code, detail=f"Simulated error {code}")


@app.get("/large")
async def large_response(size_kb: int = 100):
    """Return large response body - tests buffering through proxy."""
    # Generate ~size_kb KB of data
    data = "x" * (size_kb * 1024)
    return {"size_kb": size_kb, "data": data}


@app.get("/concurrent")
async def track_concurrent():
    """Track concurrent requests - tests async handling."""
    global _concurrent_counter, _max_concurrent
    _concurrent_counter += 1
    if _concurrent_counter > _max_concurrent:
        _max_concurrent = _concurrent_counter
    
    current = _concurrent_counter
    max_seen = _max_concurrent
    
    # Simulate some work
    await asyncio.sleep(0.1)
    
    _concurrent_counter -= 1
    
    return {
        "concurrent_at_entry": current,
        "max_concurrent_seen": max_seen,
        "worker_pid": os.getpid(),
    }


@app.get("/scope")
async def show_scope(request: Request):
    """Show ASGI scope details - debug endpoint for protocol verification."""
    return {
        "type": request.scope.get("type"),
        "path": request.scope.get("path"),
        "method": request.scope.get("method"),
        "client": list(request.scope.get("client")) if request.scope.get("client") else None,
        "server": list(request.scope.get("server")) if request.scope.get("server") else None,
        "headers_count": len(request.scope.get("headers", [])),
    }
'''

