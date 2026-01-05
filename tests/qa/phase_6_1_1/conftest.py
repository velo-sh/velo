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


class VeloServeProcess:
    """Wrapper for velo serve process with worker management."""

    def __init__(self, proc: subprocess.Popen, port: int = 8000):
        self.proc = proc
        self.port = port
        self.pid = proc.pid
        self.zygote_pid: Optional[int] = None
        self._worker_pids: List[int] = []

    def is_running(self) -> bool:
        """Check if the main process is still running."""
        return self.proc.poll() is None

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Wait for server to be ready to accept requests."""
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

    def wait_worker_ready(self, timeout: float = 5.0) -> None:
        """Wait for a worker to be ready after restart."""
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
        """Detect Zygote supervisor process PID.
        
        The true Zygote supervisor is the one whose parent is NOT a zygote process.
        Workers forked from Zygote inherit the same command line.
        """
        all_zygotes = []
        
        # 1. Collect all processes that look like zygotes
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info['name'] or "").lower()
                cmdline = " ".join(proc.info['cmdline'] or []).lower()
                if "zygote" in name or "zygote" in cmdline:
                    if "pytest" in cmdline: continue
                    all_zygotes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        if not all_zygotes:
            return

        # 2. Find the supervisor (the one whose parent is not in all_zygotes)
        zygote_pids = {p.pid for p in all_zygotes}
        for proc in all_zygotes:
            try:
                ppid = proc.ppid()
                if ppid not in zygote_pids:
                    # This is likely the supervisor
                    self.zygote_pid = proc.pid
                    return
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Fallback: lowest PID
        if all_zygotes:
            self.zygote_pid = min(p.pid for p in all_zygotes)

    def get_worker_pids(self) -> List[int]:
        """Get list of worker PIDs.
        
        Workers are forked from the Zygote, so they are children of the Zygote PID.
        """
        if not self.zygote_pid:
            self._detect_zygote_pid()
        
        if not self.zygote_pid:
            return []

        try:
            zygote_proc = psutil.Process(self.zygote_pid)
            workers = []
            # Workers are immediate children of Zygote
            for child in zygote_proc.children(recursive=False):
                # Only include workers that haven't transitioned to uvicorn/etc if needed,
                # but currently they keep the Zygote cmdline.
                workers.append(child.pid)
            return workers
        except psutil.NoSuchProcess:
            return []

    def get_metrics(self) -> dict:
        """Get server metrics (placeholder for future implementation)."""
        return {"worker_requests": {}}

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the server gracefully."""
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


class VeloServeFactory:
    """Factory for creating VeloServeProcess instances."""

    def __init__(self, tmp_path: Path, velo_binary: str):
        self.tmp_path = tmp_path
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

        proc = subprocess.Popen(
            cmd,
            cwd=self.tmp_path,
            # Use None to inherit from parent, so -s shows it
            stdout=None,
            stderr=None,
        )
        wrapper = VeloServeProcess(proc, port)
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
def velo_serve_fixture(tmp_path: Path, velo_binary: str):
    """Fixture for starting velo serve processes."""
    # Create sample app in tmp_path
    app_file = tmp_path / "main.py"
    app_file.write_text(SAMPLE_APP_CODE)

    # Create pyproject.toml to enable framework detection (required for Zygote)
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text('[project]\ndependencies = ["fastapi"]')

    factory = VeloServeFactory(tmp_path, velo_binary)
    yield factory
    factory.cleanup()


@pytest.fixture
def isolated_env(tmp_path: Path):
    """Isolated environment for tests."""
    return tmp_path


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

from fastapi import FastAPI, Request
import os
import signal

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


@app.get("/slow")
async def slow(seconds: int = 1):
    import asyncio
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
'''
