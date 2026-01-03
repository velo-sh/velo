"""
Phase 5.1 QA: Advanced Zygote Async Mode Tests
Focus: Stability (L5), Security (L4), and Edge Cases (L2).
"""

import subprocess
import time
import os
import signal
import re
from pathlib import Path
import pytest


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    cargo_path = Path(__file__).parent.parent.parent.parent / "target" / "release" / "velo"
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


class TestZygoteAsyncAdvanced:
    """
    Advanced Zygote Async Tests: Stability and Security.
    """

    @pytest.mark.stability
    def test_stab_51_001_orphan_cleanup(self, velo_binary, tmp_path):
        """
        STAB-51-001: Verify orphans are reaped when TTL expires or parent dies.
        """
        # Create a script that runs longer than TTL (we'll use a short TTL if possible)
        # Note: Current implementation has 3600s TTL by default.
        # We'll test parent-death orphaning.
        
        test_py = tmp_path / "long_run.py"
        test_py.write_text("import time; time.sleep(60)")
        
        stop_zygote(velo_binary, tmp_path)
        
        # Start Zygote with small idle timeout or kill it manually
        run_velo(["run", "--zygote", "--async", str(test_py)], tmp_path, velo_binary)
        
        # Find the worker PID
        # We need a way to get the PID. The CLI prints it to stderr.
        result = run_velo(["run", "--zygote", "--async", str(test_py)], tmp_path, velo_binary)
        import re
        match = re.search(r"PID: (\d+)", result.stderr)
        assert match, "Could not find worker PID in CLI output"
        worker_pid = int(match.group(1))
        
        # Verify worker is running
        assert os.kill(worker_pid, 0) is None
        
        # Stop Zygote (the "parent" of the worker)
        stop_zygote(velo_binary, tmp_path)
        
        # Wait for Guardian thread to detect orphaning (sleeps 10s)
        time.sleep(15)
        
        # Verify worker is dead
        with pytest.raises(ProcessLookupError):
            os.kill(worker_pid, 0)

    @pytest.mark.security
    def test_sec_51_001_log_file_path_security(self, velo_binary, tmp_path):
        """
        SEC-51-001: Prevent path traversal in background logging.
        Currently, --stdout-file is handled by the CLI passing a path to Zygote.
        """
        # Note: The CLI doesn't yet have --stdout-file flag, but internal IPC does.
        # We'll skip this until the CLI flag is added or test via IPC.
        pytest.skip("CLI flag --stdout-file not yet implemented in run.rs")

    @pytest.mark.stability
    def test_stab_51_002_rapid_spawn(self, velo_binary, tmp_path):
        """
        Burst test: Spawn 20 async workers as fast as possible.
        """
        test_py = tmp_path / "fast.py"
        test_py.write_text("print('ok')")
        
        pids = []
        start = time.perf_counter()
        for _ in range(20):
            result = run_velo(["run", "--zygote", "--async", str(test_py)], tmp_path, velo_binary)
            assert result.returncode == 0
            match = re.search(r"PID: (\d+)", result.stderr)
            if match:
                pids.append(int(match.group(1)))
        
        elapsed = time.perf_counter() - start
        print(f"Spawned 20 workers in {elapsed:.2f}s")
        assert elapsed < 2.0 # 100ms per spawn including CLI startup
        
        # Cleanup
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
