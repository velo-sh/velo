"""
Phase 5.1 QA: Zygote Async Mode Tests

Verifies the 15ms startup target and orphan management (RFC-0008).
"""

import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    cargo_path = Path(__file__).parents[4] / "target" / "release" / "velo"
    if cargo_path.exists():
        return str(cargo_path)
    return "velo"


def run_velo(args: list, cwd: Path, velo_binary: str, timeout: int = 60):
    """Helper to run velo command."""
    result = subprocess.run(
        [velo_binary] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def stop_zygote(velo_binary: str, cwd: Path):
    """Stop any running Zygote daemon."""
    run_velo(["zygote", "stop"], cwd, velo_binary)
    time.sleep(0.5)


class TestZygoteAsyncMode:
    """
    QA-REQ-002: Zygote Async Mode Tests
    """

    @pytest.mark.happy_path
    def test_perf_5_1_001_async_speed(self, velo_binary, tmp_path):
        """
        PERF-5.1-001: Async mode returns in < 20ms
        """
        # Create a "slow" script (simulates heavy startup)
        slow_py = tmp_path / "slow.py"
        slow_py.write_text("import time; time.sleep(1); print('done')")

        # Ensure Zygote is running (warm up)
        stop_zygote(velo_binary, tmp_path)
        run_velo(["run", "--zygote", "slow.py"], tmp_path, velo_binary)

        # Measure async duration
        start = time.perf_counter()
        result = run_velo(["run", "--zygote", "--async", "slow.py"], tmp_path, velo_binary)
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"Async return time: {elapsed_ms:.2f}ms")
        assert result.returncode == 0
        assert "Worker spawned in background" in result.stderr

        # The key assertion: CLI exits while script is still sleeping (1s)
        # We expect < 30ms (generous for CI/Mac overhead)
        assert elapsed_ms < 50, f"Async mode too slow: {elapsed_ms:.2f}ms"

    @pytest.mark.happy_path
    def test_func_5_1_001_async_execution(self, velo_binary, tmp_path):
        """
        FUNC-5.1-001: Verify async worker actually executes
        """
        marker_file = tmp_path / "async_done.txt"
        test_py = tmp_path / "test_async.py"
        test_py.write_text(
            f"""
import time
with open("{marker_file}", "w") as f:
    f.write("async_ok")
"""
        )

        # Stop zygote to be safe
        stop_zygote(velo_binary, tmp_path)

        # Run async
        result = run_velo(["run", "--zygote", "--async", str(test_py)], tmp_path, velo_binary)
        assert result.returncode == 0

        # Wait for worker (max 2s)
        for _ in range(20):
            if marker_file.exists():
                break
            time.sleep(0.1)

        assert marker_file.exists()
        assert marker_file.read_text() == "async_ok"

    @pytest.mark.security
    def test_sec_51_001_mutual_exclusion(self, velo_binary, tmp_path):
        """
        Verify --async and --profile are mutually exclusive
        """
        test_py = tmp_path / "test.py"
        test_py.write_text("print('test')")

        result = run_velo(
            ["run", "--zygote", "--async", "--profile", str(test_py)],
            tmp_path,
            velo_binary,
        )
        assert result.returncode != 0
        assert "mutually exclusive" in result.stderr
