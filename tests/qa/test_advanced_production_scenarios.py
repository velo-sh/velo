"""
Velo QA: Advanced Production Scenario Tests
=============================================
Expert-level testing for edge cases and SLO guarantees:
1. SLO Violation Logging Execution
2. Definitive Zombie Prevention (SIGKILL escalation)
3. Automatic Pool Prewarming (Zero-trigger)
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.p0_hardening, pytest.mark.zygote]


@pytest.fixture
def velo_binary():
    """Find the velo binary."""
    debug_path = Path(__file__).parent.parent.parent / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    release_path = Path(__file__).parent.parent.parent / "target" / "release" / "velo"
    if release_path.exists():
        return str(release_path)
    pytest.skip("velo binary not found - run cargo build first")


@pytest.fixture
def zygote_env(tmp_path):
    """Create test environment with venv structure."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (tmp_path / "uv.lock").write_text("version = 1\n")
    return tmp_path


class TestAdvancedScenarios:
    """Advanced scenarios for production-grade reliability."""

    @pytest.mark.timeout(30)
    def test_slo_violation_logging(self, zygote_env, velo_binary):
        """SLO-VIOLATION-001: Set SLO to 0 and verify warning emission."""

        env = os.environ.copy()
        env["VELO_SLO_FORK_LATENCY_MS"] = "0"
        env["VELO_TEST_MODE"] = "0"
        env["RUST_LOG"] = "velo_core=warn,warn"

        # Start Zygote
        subprocess.run([velo_binary, "zygote", "start", "--daemon"], cwd=zygote_env, env=env, check=True)
        time.sleep(2)

        try:
            script = zygote_env / "noop.py"
            script.write_text("print('hello')")

            combined_stderr = ""
            for _ in range(3):
                res = subprocess.run(
                    [velo_binary, "run", "--zygote", str(script)],
                    cwd=zygote_env,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                combined_stderr += res.stderr
                if "SLO Violation" in combined_stderr or "[SLO_DEBUG]" in combined_stderr:
                    break

            assert "[SLO_DEBUG]" in combined_stderr or "SLO Violation" in combined_stderr, (
                f"Warning missing. Stderr: {combined_stderr}"
            )

        finally:
            subprocess.run([velo_binary, "zygote", "stop"], cwd=zygote_env, env=env, capture_output=True)

    @pytest.mark.timeout(60)
    def test_definitive_zombie_prevention(self, zygote_env, velo_binary):
        """SHUTDOWN-ZOMBIE-001: Stubborn workers must be definitively reaped."""

        env = os.environ.copy()
        env["VELO_TEST_MODE"] = "1"

        subprocess.run([velo_binary, "zygote", "start", "--daemon"], cwd=zygote_env, env=env, check=True)
        time.sleep(1)

        try:
            pid_file = zygote_env / "worker.pid"
            stubborn_script = zygote_env / "stubborn.py"
            stubborn_script.write_text(f"""
import signal
import time
import os
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open('{pid_file}', 'w') as f:
    f.write(str(os.getpid()))
while True:
    time.sleep(0.1)
""")

            subprocess.run([velo_binary, "run", "--async", str(stubborn_script)], cwd=zygote_env, env=env, check=True)

            worker_pid = None
            for _ in range(50):
                if pid_file.exists():
                    try:
                        worker_pid = int(pid_file.read_text().strip())
                        break
                    except (ValueError, OSError):
                        pass
                time.sleep(0.1)

            assert worker_pid is not None, "Failed to capture worker PID"
            os.kill(worker_pid, 0)

            env_stop = env.copy()
            env_stop["VELO_DRAIN_TIMEOUT"] = "1"

            subprocess.run([velo_binary, "zygote", "stop"], cwd=zygote_env, env=env_stop, check=True)

            time.sleep(2)
            with pytest.raises(ProcessLookupError):
                os.kill(worker_pid, 0)

        finally:
            subprocess.run([velo_binary, "zygote", "stop"], cwd=zygote_env, capture_output=True)

    @pytest.mark.timeout(30)
    def test_automatic_pool_prewarming(self, zygote_env, velo_binary):
        """PREWARM-STABILITY-001: Pool should fill without external triggers."""

        env = os.environ.copy()
        env["VELO_TEST_MODE"] = "0"
        socket_path = zygote_env / "velo_prewarm.sock"
        env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

        subprocess.run([velo_binary, "zygote", "start", "--daemon"], cwd=zygote_env, env=env, check=True)

        try:
            max_retries = 20
            pool_warmed = False

            for i in range(max_retries):
                time.sleep(1)
                result = subprocess.run(
                    [velo_binary, "zygote", "status"], cwd=zygote_env, env=env, capture_output=True, text=True
                )
                match = re.search(r"Pool:\s*(\d+)\s*idle", result.stdout)
                if match and int(match.group(1)) >= 1:
                    pool_warmed = True
                    break
                print(f"DEBUG {i}: {result.stdout}")

            assert pool_warmed, f"Pool failed to prewarm. Latest status: {result.stdout}"
        finally:
            subprocess.run([velo_binary, "zygote", "stop"], cwd=zygote_env, env=env, capture_output=True)
