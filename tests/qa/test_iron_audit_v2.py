"""
Adversarial Audit V2: Deep RFC-0030 Compliance Check

Targets:
1. 'velo jupyter install' must include --zygote in kernel.json.
2. 'velo run --zygote --async -m module' must actually support async_mode.
3. VeloSpawner must use 'velo run' to avoid 'broken pipe' or 'command not found'.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest


def get_velo_binary() -> str:
    project_root = Path(__file__).parent.parent.parent
    debug_binary = project_root / "target" / "debug" / "velo"
    return str(debug_binary) if debug_binary.exists() else "velo"


VELO_BINARY = get_velo_binary()


@pytest.mark.qa
class TestRFC0030IronAuditV2:
    def test_jupyter_kernel_json_content(self, tmp_path):
        """DEFECT-001: kernel.json missing --zygote flag."""
        # Use a temporary directory for kernels to avoid polluting system
        env = os.environ.copy()
        env["JUPYTER_DATA_DIR"] = str(tmp_path)

        subprocess.run([VELO_BINARY, "jupyter", "install"], env=env, check=True)

        # Locate kernel.json
        kernel_file = next(tmp_path.glob("kernels/velo/kernel.json"))
        with open(kernel_file) as f:
            data = json.load(f)

        argv = data.get("argv", [])
        print(f"\n[QA] Generated argv: {argv}")

        # RFC-0030 §3.3: Must include --zygote for auto-acceleration
        assert "--zygote" in argv or "run" in argv and "--zygote" in argv, (
            "CRITICAL GAP: kernel.json is missing the --zygote flag. Acceleration will not be automatic."
        )

    def test_run_module_async_mode_propagation(self):
        """DEFECT-002: Rust code hardcodes async_mode=false in run_module_impl."""
        # Reset Zygote
        subprocess.run([VELO_BINARY, "zygote", "stop"], capture_output=True)
        subprocess.run([VELO_BINARY, "zygote", "start", "--daemon"], check=True)
        time.sleep(1)

        # Run a module in async mode.
        # If propagated correctly, it should exit IMMEDIATELY and print 'Worker PID: ...'
        start = time.perf_counter()
        result = subprocess.run(
            [VELO_BINARY, "run", "--zygote", "--async", "-m", "time", "--", "-c", "import time; time.sleep(5)"],
            capture_output=True,
            text=True,
        )
        elapsed = time.perf_counter() - start

        print(f"\n[QA] Async execution took {elapsed:.2f}s")
        print(f"[QA] Output: {result.stdout}")

        # If it waited 5 seconds, it's NOT async
        assert elapsed < 1.0, f"DEFECT: --async was ignored! Execution took {elapsed:.2f}s"
        assert "Worker PID:" in result.stdout, "DEFECT: Missing 'Worker PID' output for async execution"

    def test_spawner_logic_audit(self):
        """DEFECT-003: VeloSpawner in Python returns incorrect command structure."""
        # We manually import the spawner to audit its logic
        import sys
        from unittest.mock import MagicMock

        # Mock jupyterhub
        sys.modules["jupyterhub"] = MagicMock()
        sys.modules["jupyterhub.spawner"] = MagicMock()
        sys.modules["traitlets"] = MagicMock()

        # Import from the repo path
        sys.path.append(os.path.join(os.getcwd(), "python"))
        from jupyterhub_velo.spawner import VeloSpawner

        spawner = VeloSpawner()
        spawner.cmd = ["python", "-m", "ipykernel_launcher"]

        # Audit entrypoint
        final_cmd = spawner.cmd
        print(f"\n[QA] Spawner cmd: {final_cmd}")
        assert "velo" in str(final_cmd), "Spawner must use 'velo' entrypoint"
        assert "run" in str(final_cmd) or "run" in str(spawner.get_args()), (
            "DEFECT: Spawner is missing the 'run' command. Execution will fail."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
