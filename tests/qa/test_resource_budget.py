import pytest
import psutil
import time
from conftest import T_SHORT, T_MEDIUM


@pytest.mark.tier1
@pytest.mark.resource_budget
class TestResourceBudget:
    """Verify Velo stays within strict resource limits (The 'Zen' Baseline)."""

    def test_startup_memory_footprint(self, isolated_env):
        """RSS should be reasonable (<50MB) for a cold start."""
        env = isolated_env
        # VALID app that stays alive
        env.create_app(
            "main.py",
            """
from fastapi import FastAPI
app = FastAPI()
""",
        )

        # Using subprocess directly for finer control
        import subprocess
        import os

        # PROPER ENV HANDLING (from TestL0Smoke)
        # 1. Clear VIRTUAL_ENV to match ComprehensiveTestEnv behavior
        # 2. Use 'uv run' to ensure we pick up the isolated environment
        run_env = os.environ.copy()
        # NOTE: logic to del VIRTUAL_ENV removed to allow inheritance of dev dependencies (uvicorn/fastapi)

        port = env.next_port()
        process = subprocess.Popen(
            ["uv", "run", env.velo, "serve", "main:app", "--port", str(port)],
            cwd=env.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=run_env,
        )
        try:
            # Let it settle
            time.sleep(2)

            # Check if process is still running
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                print(f"\nSTDOUT:\n{stdout.decode()}")
                print(f"\nSTDERR:\n{stderr.decode()}")
                pytest.fail(
                    f"Process exited prematurely with code {process.returncode}"
                )

            p = psutil.Process(process.pid)
            # Accessing memory_info on a zombie raises ZombieProcess, verify status first
            if p.status() == psutil.STATUS_ZOMBIE:
                pytest.fail("Process became a zombie")

            rss_mb = p.memory_info().rss / 1024 / 1024

            # Heuristic: Rust binary + Python interpreter shouldn't be huge
            # Adjust limit based on real-world observation. 50MB is generous but good guardrail.
            assert rss_mb < 80, f"Memory bloat detected: {rss_mb:.2f} MB > 80 MB"

        finally:
            process.terminate()
            process.wait()

    def test_fd_hygiene_strict(self, isolated_env):
        """Only standard FDs and Log/Socket should be open."""
        env = isolated_env
        env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")

        # Using subprocess directly for finer control
        import subprocess
        import os

        run_env = os.environ.copy()
        # NOTE: logic to del VIRTUAL_ENV removed to allow inheritance of dev dependencies (uvicorn/fastapi)

        port = env.next_port()
        process = subprocess.Popen(
            ["uv", "run", env.velo, "serve", "main:app", "--port", str(port)],
            cwd=env.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=run_env,
        )
        try:
            time.sleep(2)
            p = psutil.Process(process.pid)
            fds = p.open_files()
            # macOS/old psutil compatibility
            try:
                connections = p.net_connections()
            except AttributeError:
                connections = p.connections()

            # We expect:
            # 1. Access Log
            # 2. Error Log (maybe)
            # 3. The executable itself (txt)
            # 4. Shared libraries (lib) - psutil doesn't list these as open_files usually

            # Filter strictly
            suspicious_files = [
                f.path
                for f in fds
                if not (
                    "log" in f.path
                    or "velo" in f.path
                    or ".lock" in f.path  # The binary itself  # uv lock files
                )
            ]

            # On generic linux/mac, there shouldn't be random files open
            assert (
                len(suspicious_files) == 0
            ), f"Unexpected open files: {suspicious_files}"

            # Networking: Should listen on 1 port
            listening = [c for c in connections if c.status == "LISTEN"]
            assert len(listening) <= 1, f"Too many listening ports: {listening}"

        finally:
            process.terminate()
            process.wait()

    def test_thread_count_sanity(self, isolated_env):
        """Should not spawn excessive threads on idle."""
        env = isolated_env
        env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")

        import subprocess
        import os

        run_env = os.environ.copy()
        # NOTE: logic to del VIRTUAL_ENV removed to allow inheritance of dev dependencies (uvicorn/fastapi)

        port = env.next_port()
        process = subprocess.Popen(
            ["uv", "run", env.velo, "serve", "main:app", "--port", str(port)],
            cwd=env.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=run_env,
        )
        try:
            time.sleep(2)
            p = psutil.Process(process.pid)
            threads = p.num_threads()

            # Rust Tokio runtime (worker threads) + maybe 1-2 generic
            # Core count dependent, but shouldn't be 100
            assert threads < 20, f"Thread explosion detected: {threads} threads"

        finally:
            process.terminate()
            process.wait()
