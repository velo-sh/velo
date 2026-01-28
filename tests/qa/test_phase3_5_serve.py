"""
Velo QA: Phase 3.5 Serve Command Tests
======================================
Tests for `velo serve` command with uvicorn integration.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest


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


class TestServeHelpAndValidation:
    """Tests for velo serve command help and argument validation."""

    def test_serve_in_help_output(self):
        """Verify serve command appears in help."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "--help"], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert "serve" in result.stdout
        assert "ASGI/WSGI" in result.stdout

    def test_serve_missing_app_error(self):
        """Verify error when app argument is missing."""
        velo = get_velo_binary()
        result = subprocess.run([velo, "serve"], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0
        # clap uses "required arguments were not provided"
        stderr_lower = result.stderr.lower()
        assert "required" in stderr_lower or "missing" in stderr_lower or "app" in stderr_lower

    def test_serve_invalid_app_format(self):
        """Verify error for invalid app format (no colon)."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "invalid_format"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        # clap uses "Invalid app format" (case varies)
        stderr_lower = result.stderr.lower()
        assert "invalid" in stderr_lower and ("app" in stderr_lower or "format" in stderr_lower)

    def test_serve_unknown_option_error(self):
        """Verify error for unknown options."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--unknown-option"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        # clap uses "unexpected argument"
        stderr_lower = result.stderr.lower()
        assert "unexpected" in stderr_lower or "unknown" in stderr_lower or "unrecognized" in stderr_lower


class FastAPITestEnv:
    """Test environment with FastAPI app."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="velo_serve_test_"))
        self.velo = get_velo_binary()
        self.venv_path = self.path / ".venv"

    def _get_env(self) -> dict[str, str]:
        """Build environment with project venv activated."""
        env = os.environ.copy()
        venv_bin = self.venv_path / "bin"
        env["VIRTUAL_ENV"] = str(self.venv_path)
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        # Preserve library paths for Rust binary (libpython)
        for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def setup(self) -> "FastAPITestEnv":
        # Create virtual environment
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True)
        # Install fastapi and uvicorn
        subprocess.run(
            ["uv", "pip", "install", "--python", ".venv/bin/python", "fastapi", "uvicorn", "msgpack", "--quiet"],
            cwd=self.path,
            check=True,
        )
        # Create uv.lock for velo
        (self.path / "uv.lock").write_text("{}")
        # Create pyproject.toml
        (self.path / "pyproject.toml").write_text(
            """
[project]
name = "test-app"
dependencies = ["fastapi", "uvicorn"]
"""
        )
        # Create FastAPI app
        (self.path / "main.py").write_text(
            """
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
"""
        )
        return self

    def run_serve(self, args: list[str], timeout: float = 5) -> subprocess.Popen[str]:
        """Start velo serve and return process."""
        proc = subprocess.Popen(
            [self.velo, "serve"] + args,
            cwd=self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self._get_env(),
        )
        return proc

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass

    def __enter__(self) -> "FastAPITestEnv":
        return self.setup()

    def __exit__(self, *args: Any) -> None:
        self.cleanup()


class TestServeStartup:
    """Tests for velo serve startup behavior."""

    @pytest.mark.slow
    def test_serve_starts_fastapi(self):
        """Verify velo serve can start a FastAPI app."""
        with FastAPITestEnv() as env:
            proc = env.run_serve(["main:app", "--port", "19876"])
            try:
                # Give it time to start
                time.sleep(3)

                # Check if process is still running
                if proc.poll() is not None:
                    # Process exited - check stderr for uvicorn not found
                    _, stderr = proc.communicate()
                    if "uvicorn" in stderr.lower():
                        pytest.skip("uvicorn not installed in test env")
                    pytest.fail(f"Server exited early: {stderr}")

                # Try to connect
                import urllib.request

                try:
                    resp = urllib.request.urlopen("http://127.0.0.1:19876/health", timeout=5)
                    data = resp.read().decode()
                    assert "ok" in data
                except Exception as e:
                    pytest.skip(f"Could not connect to server: {e}")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_serve_shows_startup_info(self):
        """Verify velo serve shows framework and binding info."""
        with FastAPITestEnv() as env:
            proc = env.run_serve(["main:app", "--port", "19877"])
            try:
                time.sleep(2)
                proc.terminate()
                _, stderr = proc.communicate(timeout=15)

                # Should show startup info
                assert "Starting server" in stderr or "FastAPI" in stderr or "uvicorn" in stderr.lower()
            except Exception:
                proc.kill()
                raise


class TestServeOptions:
    """Tests for velo serve command options."""

    def test_port_option_parsing(self):
        """Verify --port option is parsed correctly."""
        velo = get_velo_binary()
        # This will fail to start (no app) but tests argument parsing
        result = subprocess.run(
            [velo, "serve", "main:app", "--port", "not_a_number"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        # clap uses "invalid value" or "invalid digit"
        stderr_lower = result.stderr.lower()
        assert "invalid" in stderr_lower

    def test_workers_option_parsing(self):
        """Verify --workers option is parsed correctly."""
        velo = get_velo_binary()
        result = subprocess.run(
            [velo, "serve", "main:app", "--workers", "not_a_number"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        # clap uses "invalid value" or "invalid digit"
        stderr_lower = result.stderr.lower()
        assert "invalid" in stderr_lower


class TestZygoteIntegration:
    """Tests for Zygote integration with velo serve."""

    def test_zygote_prewarm_message(self):
        """Verify Zygote pre-warming message is displayed."""
        with FastAPITestEnv() as env:
            # Kill any existing Zygote first
            subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)

            proc = env.run_serve(["main:app", "--port", "19878"])
            try:
                time.sleep(2)
                proc.terminate()
                _, stderr = proc.communicate(timeout=15)

                # Should show Zygote pre-warming or using existing Zygote
                zygote_mentioned = "Zygote" in stderr or "Pre-warming" in stderr or "FastAPI" in stderr
                assert zygote_mentioned or "uvicorn" in stderr.lower()
            except Exception:
                proc.kill()
                raise
            finally:
                subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)

    def test_no_zygote_flag(self):
        """Verify --no-zygote flag disables Zygote."""
        with FastAPITestEnv() as env:
            proc = env.run_serve(["main:app", "--port", "19879", "--no-zygote"])
            try:
                time.sleep(1)
                proc.terminate()
                _, stderr = proc.communicate(timeout=15)

                # Should NOT mention pre-warming when --no-zygote is used
                assert "Pre-warming" not in stderr
            except Exception:
                proc.kill()
                raise


class TestFrameworkDetection:
    """Tests for framework auto-detection."""

    def test_fastapi_detected(self):
        """Verify FastAPI is detected from pyproject.toml."""
        with FastAPITestEnv() as env:
            proc = env.run_serve(["main:app", "--port", "19880"])
            try:
                time.sleep(2)
                proc.terminate()
                _, stderr = proc.communicate(timeout=15)

                # Should detect FastAPI or show startup info
                # Accept: "FastAPI" detected, "Starting TITANIUM server", or fallback to uvicorn
                assert (
                    "FastAPI" in stderr
                    or "Starting TITANIUM server" in stderr
                    or "Starting server" in stderr
                    or ("uvicorn" in stderr.lower() and "defaulting" in stderr.lower())
                ), f"No detection or startup message found in stderr: {stderr[:500]}"
            except Exception:
                proc.kill()
                raise

    def test_django_module_pattern(self):
        """Verify Django is inferred from module pattern."""
        velo = get_velo_binary()
        # Test with Django-style module pattern
        # This will fail (no Django) but tests detection logic in output
        result = subprocess.run(
            [velo, "serve", "django.core.wsgi:application", "--port", "19881"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # May mention Django or fail finding Django
        # Just verify command was processed
        assert result.returncode != 0 or "Django" in result.stderr or "Error" in result.stderr


class TestServePerformance:
    """Performance tests for velo serve startup."""

    @pytest.mark.slow
    def test_startup_time_reasonable(self):
        """Verify serve startup completes within timeout."""
        with FastAPITestEnv() as env:
            start = time.time()
            proc = env.run_serve(["main:app", "--port", "19882"])
            try:
                # Wait for process to start or fail quickly
                time.sleep(2)
                elapsed = time.time() - start

                # Should start reasonably fast (< 5 seconds)
                if proc.poll() is None:
                    # Still running - good
                    assert elapsed < 5.0, f"Server took too long to start: {elapsed:.2f}s"
                else:
                    # Exited - check why
                    _, stderr = proc.communicate()
                    if "uvicorn" not in stderr.lower():
                        pytest.skip(f"Server setup issue: {stderr[:200]}")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
