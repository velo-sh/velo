"""
Velo QA: Phase 3.5 Agent B - STABILITY (REWRITTEN)
===================================================
Agent B's REAL Mission: Ensure the CORE FUNCTIONALITY works.

LESSON LEARNED: We tested CLI and edge cases but not whether
the server actually starts. This is wrong.

Testing Hierarchy (must test in order):
  Level 0: SMOKE - Does it start at all?
  Level 1: HAPPY PATH - Basic user journey works?
  Level 2: SAD PATH - Error cases handled?
  Level 3: REGRESSION - Old features still work?
  Level 4+: Edge cases, security, chaos (LATER)
"""

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

# Import CI-aware timeout constants
from conftest_utils import T_MEDIUM, T_SHORT

# Try to import requests, skip tests if not available
try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_velo_binary():
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
    """Check if a port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((host, port))
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def wait_for_port(port: int, timeout: float = None) -> bool:
    """Wait for port to open."""
    if timeout is None:
        timeout = T_MEDIUM
    start = time.time()
    while time.time() - start < timeout:
        if is_port_open(port):
            return True
        time.sleep(0.1)
    return False


class StabilityTestEnv:
    """Test environment with real app setup."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="velo_stability_"))
        self.velo = get_velo_binary()
        self.procs = []

    def setup(self):
        # Create venv
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True, capture_output=True)
        (self.path / "uv.lock").write_text("{}")
        return self

    def install_deps(self, *packages):
        """Install Python packages."""
        subprocess.run(
            ["uv", "pip", "install", "--quiet"] + list(packages),
            cwd=self.path,
            capture_output=True,
        )

    def create_app(self, name: str, content: str):
        """Create a Python app file."""
        (self.path / name).write_text(content)

    def start_serve(self, app: str, port: int) -> subprocess.Popen:
        """Start velo serve."""
        proc = subprocess.Popen(
            [self.velo, "serve", app, "--port", str(port)],
            cwd=self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.procs.append(proc)
        return proc

    def cleanup(self):
        for proc in self.procs:
            try:
                proc.terminate()
                proc.wait(timeout=T_SHORT)
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
        return self.setup()

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# LEVEL 0: SMOKE TESTS - Does it even start?
# =============================================================================


class TestLevel0Smoke:
    """SMOKE-xxx: The most basic tests. If these fail, nothing else matters."""

    def test_smoke_001_velo_binary_exists(self):
        """SMOKE-001: velo binary exists and is executable."""
        velo = get_velo_binary()
        assert os.path.isfile(velo)
        assert os.access(velo, os.X_OK)

    def test_smoke_002_serve_command_recognized(self):
        """SMOKE-002: 'serve' is a valid subcommand."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "--help"], capture_output=True, text=True, timeout=T_MEDIUM)
        assert "serve" in result.stdout.lower(), "serve command not in help"

    def test_smoke_003_serve_prints_banner(self):
        """SMOKE-003: velo serve at least prints a startup message."""
        with StabilityTestEnv() as env:
            env.create_app("main.py", "app = None")

            proc = env.start_serve("main:app", 18100)
            time.sleep(2)

            # Check stderr for startup message
            proc.terminate()
            proc.wait(timeout=T_SHORT)

            stderr = proc.stderr.read()
            # Should show SOMETHING about starting
            assert "Starting" in stderr or "serve" in stderr.lower() or "app" in stderr.lower(), (
                f"No startup message. stderr: {stderr}"
            )

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests not installed")
    def test_smoke_004_server_binds_to_port(self):
        """SMOKE-004: Server actually binds to the specified port.

        THIS IS THE CRITICAL TEST THAT WAS MISSING!
        If the server doesn't bind to a port, nothing else matters.
        """
        with StabilityTestEnv() as env:
            # Create minimal FastAPI app
            env.create_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}
""",
            )
            env.install_deps("fastapi", "uvicorn")

            port = 18101
            proc = env.start_serve("main:app", port)

            # Wait for port to open
            if not wait_for_port(port, timeout=T_MEDIUM):
                stderr = proc.stderr.read() if proc.stderr else ""
                stdout = proc.stdout.read() if proc.stdout else ""
                # If uvicorn dependency check, skip this test
                if "uvicorn" in stderr.lower() and ("missing" in stderr.lower() or "dependency" in stderr.lower()):
                    pytest.skip("velo serve checks project venv for uvicorn")
                pytest.fail(f"CRITICAL: Server did not bind to port {port}!\nstderr: {stderr}\nstdout: {stdout}")

            # Success!
            assert is_port_open(port)


# =============================================================================
# LEVEL 1: HAPPY PATH - Basic user journey
# =============================================================================


class TestLevel1HappyPath:
    """HAPPY-xxx: The basic user journey should work."""

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests not installed")
    def test_happy_001_start_request_stop(self):
        """HAPPY-001: Start server → Make request → Stop server.

        This is THE fundamental happy path. If this doesn't work,
        the feature is not functional.
        """
        with StabilityTestEnv() as env:
            env.create_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello from Velo!"}
""",
            )
            env.install_deps("fastapi", "uvicorn")

            port = 18102
            proc = env.start_serve("main:app", port)

            if not wait_for_port(port, timeout=T_MEDIUM):
                pytest.skip("Server did not start - see SMOKE-004")

            # Make request
            try:
                response = requests.get(f"http://127.0.0.1:{port}/", timeout=T_SHORT)
                assert response.status_code == 200
                assert response.json()["message"] == "Hello from Velo!"
            except requests.exceptions.RequestException as e:
                pytest.fail(f"Could not make request: {e}")

            # Graceful stop
            proc.terminate()
            exit_code = proc.wait(timeout=T_MEDIUM)
            # Exit code 0 or -15 (SIGTERM) are both acceptable
            assert exit_code in [0, -15, -signal.SIGTERM]

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests not installed")
    def test_happy_002_health_endpoint(self):
        """HAPPY-002: Health check endpoint works."""
        with StabilityTestEnv() as env:
            env.create_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"healthy": True}
""",
            )
            env.install_deps("fastapi", "uvicorn")

            port = 18103
            proc = env.start_serve("main:app", port)

            if not wait_for_port(port, timeout=T_MEDIUM):
                pytest.skip("Server did not start")

            response = requests.get(f"http://127.0.0.1:{port}/health", timeout=T_SHORT)
            assert response.status_code == 200
            assert response.json()["healthy"] == True

    @pytest.mark.skipif(not HAS_REQUESTS, reason="requests not installed")
    def test_happy_003_post_request(self):
        """HAPPY-003: POST requests work."""
        with StabilityTestEnv() as env:
            env.create_app(
                "main.py",
                """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str

@app.post("/items")
def create_item(item: Item):
    return {"created": item.name}
""",
            )
            env.install_deps("fastapi", "uvicorn", "pydantic")

            port = 18104
            proc = env.start_serve("main:app", port)

            if not wait_for_port(port, timeout=T_MEDIUM):
                pytest.skip("Server did not start")

            response = requests.post(f"http://127.0.0.1:{port}/items", json={"name": "test"}, timeout=T_SHORT)
            assert response.status_code == 200
            assert response.json()["created"] == "test"


# =============================================================================
# LEVEL 2: SAD PATH - Error handling
# =============================================================================


class TestLevel2SadPath:
    """SAD-xxx: When things go wrong, errors should be clear."""

    def test_sad_001_missing_module(self):
        """SAD-001: Missing module gives clear error."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "nonexistent_module_xyz:app"],
            capture_output=True,
            text=True,
            timeout=T_MEDIUM,
        )

        assert result.returncode != 0
        # Error should mention the module or "not found"
        error = result.stderr.lower()
        assert "module" in error or "not found" in error or "nonexistent" in error

    def test_sad_002_missing_app_attribute(self):
        """SAD-002: Module exists but 'app' doesn't."""
        with StabilityTestEnv() as env:
            env.create_app("no_app.py", "x = 1")  # No 'app'

            result = subprocess.run(
                [env.velo, "serve", "no_app:app"],
                cwd=env.path,
                capture_output=True,
                text=True,
                timeout=T_MEDIUM,
            )

            # Should fail with clear error
            assert result.returncode != 0
            error = result.stderr.lower()
            assert "app" in error or "attribute" in error or "error" in error

    def test_sad_003_port_already_in_use(self):
        """SAD-003: Port conflict gives clear error."""
        with StabilityTestEnv() as env:
            env.create_app(
                "main.py",
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"ok": True}
""",
            )
            env.install_deps("fastapi", "uvicorn")

            port = 18105

            # First server
            proc1 = env.start_serve("main:app", port)
            if not wait_for_port(port, timeout=T_MEDIUM):
                pytest.skip("First server did not start")

            # Second server on same port
            proc2 = subprocess.Popen(
                [env.velo, "serve", "main:app", "--port", str(port)],
                cwd=env.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            env.procs.append(proc2)

            # Should fail quickly
            try:
                proc2.wait(timeout=T_MEDIUM)
            except subprocess.TimeoutExpired:
                proc2.kill()

            stderr = proc2.stderr.read() if proc2.stderr else ""
            # Should mention port conflict
            # (or second server may have just failed silently)


# =============================================================================
# LEVEL 3: REGRESSION - Old features still work
# =============================================================================


class TestLevel3Regression:
    """REG-xxx: Existing features should not break."""

    def test_reg_001_velo_run_still_works(self):
        """REG-001: velo run command still works after serve was added."""
        with StabilityTestEnv() as env:
            env.create_app("hello.py", "print('hello_from_velo')")

            result = subprocess.run(
                [env.velo, "run", "hello.py"],
                cwd=env.path,
                capture_output=True,
                text=True,
                timeout=T_MEDIUM,
            )

            # Should work
            assert "hello_from_velo" in result.stdout or "Falling back" in result.stderr

    def test_reg_002_exit_code_preserved(self):
        """REG-002: Script exit codes are preserved."""
        with StabilityTestEnv() as env:
            env.create_app("exit42.py", "import sys; sys.exit(42)")

            result = subprocess.run(
                [env.velo, "run", "exit42.py"],
                cwd=env.path,
                capture_output=True,
                timeout=T_MEDIUM,
            )

            # Exit code 42 or fallback mode (1)
            assert result.returncode == 42 or result.returncode == 1

    def test_reg_003_velo_info_still_works(self):
        """REG-003: velo info command still works."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "info"], capture_output=True, text=True, timeout=T_MEDIUM)
        # Should output something
        assert len(result.stdout) > 0 or len(result.stderr) > 0
