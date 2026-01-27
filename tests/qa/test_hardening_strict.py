"""
Velo QA: Strict Hardening Verification (Phase 2)
==============================================
Tests for Feature Gates (Metrics/Tracing) and Zygote Circuit Breaker.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.p0_hardening, pytest.mark.zygote]


@pytest.fixture
def velo_binary():
    """Find the velo binary."""
    debug_path = Path(__file__).parent.parent.parent / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    pytest.skip("velo binary not found - run cargo build first")


@pytest.fixture
def test_env(tmp_path):
    """Setup a project environment."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (tmp_path / "uv.lock").write_text("version = 1\n")
    (tmp_path / "app.py").write_text("print('WORKER_SUCCESS')")

    # Isolation: Use a private, SHORT socket directory in /tmp
    # Pytest temp dirs are often too long for Unix sockets on macOS
    import uuid

    uid = uuid.uuid4().hex[:8]
    socket_dir = Path(f"/tmp/v_qa_{uid}")
    if socket_dir.exists():
        shutil.rmtree(socket_dir)
    socket_dir.mkdir()

    env = os.environ.copy()
    env["VELO_STRICT_OPTIMIZATIONS"] = "0"
    env["VELO_SOCKET_DIR"] = str(socket_dir)
    env["RUST_LOG"] = "velo_core=info"

    yield tmp_path, env

    # Cleanup
    if socket_dir.exists():
        shutil.rmtree(socket_dir)


class TestFeatureGates:
    """FG: Verification of metrics and tracing gates."""

    def test_fg_metrics_disabled(self, velo_binary, test_env):
        """FG-01: Metrics Disabled -> No latency logs."""
        root, sdir = test_env
        env = os.environ.copy()
        env["VELO_METRICS_ENABLED"] = "false"
        env["VELO_SOCKET_DIR"] = str(sdir)
        env["RUST_LOG"] = "velo_core=debug"

        # Start Zygote properly to ensure success fork
        subprocess.run([velo_binary, "zygote", "start"], cwd=root, env=env, check=True)

        res = subprocess.run(
            [velo_binary, "run", "--zygote", "app.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )

        assert "WORKER_SUCCESS" in res.stdout
        assert "Fork latency" not in res.stderr

    def test_fg_metrics_enabled(self, velo_binary, test_env):
        """FG-02: Metrics Enabled -> Latency logs present."""
        root, sdir = test_env
        env = os.environ.copy()
        env["VELO_METRICS_ENABLED"] = "true"
        env["VELO_SOCKET_DIR"] = str(sdir)
        env["RUST_LOG"] = "velo_core=debug"

        subprocess.run([velo_binary, "zygote", "start"], cwd=root, env=env, check=True)

        res = subprocess.run(
            [velo_binary, "run", "--zygote", "app.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )

        assert "WORKER_SUCCESS" in res.stdout
        assert "Fork latency" in res.stderr

    def test_fg_slo_violation(self, velo_binary, test_env):
        """FG-03: SLO Violation -> Warning log."""
        root, sdir = test_env
        env = os.environ.copy()
        env["VELO_METRICS_ENABLED"] = "true"
        env["VELO_SLO_FORK_LATENCY_MS"] = "0"  # Force violation
        env["VELO_SOCKET_DIR"] = str(sdir)
        env["RUST_LOG"] = "velo_core=warn"

        subprocess.run([velo_binary, "zygote", "start"], cwd=root, env=env, check=True)

        res = subprocess.run(
            [velo_binary, "run", "--zygote", "app.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )

        assert "SLO Violation" in res.stderr


class TestCircuitBreakerStrict:
    """CB: Verification of Zygote Circuit Breaker."""

    def test_cb_e2e_trip_and_fallback(self, velo_binary, test_env):
        """CB-01 & CB-02: Trip and Fallback E2E."""
        root, env = test_env
        sdir = Path(env["VELO_SOCKET_DIR"])

        # Force failure by creating a directory where a socket should be
        fail_socket = sdir / "fail.sock"
        fail_socket.mkdir()
        env["VELO_ZYGOTE_SOCKET"] = str(fail_socket)
        env["VELO_ZYGOTE_SOCKET_TIMEOUT"] = "1"
        # Use default threshold 3

        # 1st Failure
        subprocess.run([velo_binary, "run", "--zygote", "app.py"], cwd=root, env=env)
        # 2nd Failure
        subprocess.run([velo_binary, "run", "--zygote", "app.py"], cwd=root, env=env)

        # 3rd Failure: Should TRIP and fallback
        res3 = subprocess.run(
            [velo_binary, "run", "--zygote", "app.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "TRIPPED" in res3.stderr
        assert "WORKER_SUCCESS" in res3.stdout

        # 4th Call: Should be pre-emptively OPEN
        res4 = subprocess.run(
            [velo_binary, "run", "--zygote", "app.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "is OPEN" in res4.stderr
        assert "WORKER_SUCCESS" in res4.stdout

    def test_cb_auto_reset(self, velo_binary, test_env):
        """CB-03: Auto-reset upon success."""
        root, env = test_env
        sdir = Path(env["VELO_SOCKET_DIR"])

        # 1. Trip it
        env_fail = env.copy()
        fail_socket = sdir / "fail_reset.sock"
        fail_socket.mkdir()
        env_fail["VELO_ZYGOTE_SOCKET"] = str(fail_socket)
        env_fail["VELO_ZYGOTE_SOCKET_TIMEOUT"] = "1"
        subprocess.run([velo_binary, "run", "--zygote", "app.py"], cwd=root, env=env_fail)

        state_file = sdir / "circuit_breaker.state"
        assert state_file.exists(), f"State file not found at {state_file}"

        # 2. Fix environment (start real Zygote)
        fail_socket.rmdir()
        subprocess.run([velo_binary, "zygote", "start"], cwd=root, env=env, check=True)
        # Note: 'zygote start' now resets the CB itself
        assert not state_file.exists()

        # 3. Successful run -> Should work normally
        res = subprocess.run(
            [velo_binary, "run", "--zygote", "app.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "OPEN" not in res.stderr
        assert "WORKER_SUCCESS" in res.stdout
