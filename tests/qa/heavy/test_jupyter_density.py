"""
QA: Jupyter Density Verification (Gate C)

Verifies that Velo can support 100 concurrent Jupyter kernels in <5GB RSS.
Target: 100 kernels * ~20MB private + 500MB shared = ~2.5GB (Target <5GB)
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
import pytest


@pytest.fixture
def velo_binary():
    root = Path(__file__).parent.parent.parent.parent
    debug_path = root / "target" / "debug" / "velo"
    if debug_path.exists():
        path = str(debug_path.absolute())
        print(f"DEBUG: Using Velo Binary: {path}")
        # Verify version
        res = subprocess.run([path, "--version"], capture_output=True, text=True)
        print(f"DEBUG: Velo Version: {res.stdout.strip()}")
        return path
    return "velo"


def get_total_rss(pids: list[int]) -> int:
    """Calculate total RSS for a list of PIDs."""
    total = 0
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            total += proc.memory_info().rss
        except psutil.NoSuchProcess:
            continue
    return total


def test_jupyter_density_100_kernels(velo_binary: Any, tmp_path: Path) -> None:
    """
    Gate C: 100 kernels in <5GB RSS.
    """
    # 1. Setup a mock ipykernel_launcher that imports heavy libs
    # We want to simulate a real scientific stack kernel.
    mock_kernel_dir = tmp_path / "ipykernel_launcher"
    mock_kernel_dir.mkdir()
    (mock_kernel_dir / "__init__.py").write_text("")
    (mock_kernel_dir / "__main__.py").write_text("""
import sys
import time
import os

# Simulate heavy imports if available, otherwise just use memory
try:
    import numpy as np
    # Force a large allocation that stays in memory
    _data = np.zeros((1000, 1000))
except ImportError:
    # Fallback to pure python memory pressure
    _data = [0] * (10**6)

# Stay alive until killed
print(f"KERNEL_READY_PID_{os.getpid()}")
sys.stdout.flush()
while True:
    time.sleep(1)
""")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)

    # 2. Start Zygote with preload
    # Preload numpy to ensure it's shared via COW
    subprocess.run([velo_binary, "zygote", "stop"], capture_output=True)
    time.sleep(1)

    print("🚀 Starting Zygote with preload...")
    # Note: Preloading 'numpy' if available
    start_res = subprocess.run(
        [velo_binary, "zygote", "start", "--daemon", "--preload", "numpy"], capture_output=True, text=True, env=env
    )
    if start_res.returncode != 0:
        print(f"Warning: Zygote start failed (maybe numpy not found): {start_res.stderr}")
        # Try without preload
        subprocess.run([velo_binary, "zygote", "start", "--daemon"], env=env)

    time.sleep(2)

    # 3. Spawn 100 kernels concurrently (Thundering Herd)
    import concurrent.futures

    processes = []

    print("🔋 Spawning 100 kernels concurrently (Thundering Herd)...")
    start_spawn = time.time()
    all_pids = []

    def spawn_kernel(i):
        p = subprocess.Popen(
            [velo_binary, "run", "--zygote", "-m", "ipykernel_launcher"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        # Read lines until we find the PID marker
        pid = None
        while True:
            assert p.stdout is not None
            line = p.stdout.readline()
            if not line:
                break
            if "KERNEL_READY_PID_" in line:
                try:
                    pid = int(line.strip().split("_")[-1])
                    break
                except ValueError:
                    pass
        return pid, p

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(spawn_kernel, i): i for i in range(100)}
        for f in concurrent.futures.as_completed(futures):
            pid, p = f.result()
            if pid:
                all_pids.append(pid)
            processes.append(p)

    spawn_duration = time.time() - start_spawn
    print(f"⏱️  Spawned {len(all_pids)} verified kernels in {spawn_duration:.2f}s")

    # 4. Measure Memory
    if not all_pids:
        print("❌ No kernels reported ready!")
        # Drain stderr for debugging
        for p in processes[:1]:
            _, err = p.communicate(timeout=1)
            print(f"Sample Kernel Error: {err}")
    else:
        total_rss = get_total_rss(all_pids)
        total_gb = total_rss / (1024**3)
        print(f"📊 Total RSS for {len(all_pids)} kernels: {total_gb:.2f} GB")

    # Cleanup
    for p in processes:
        p.terminate()
    subprocess.run([velo_binary, "zygote", "stop"])

    # Assert Gate C
    assert len(all_pids) >= 100, f"Expected 100 kernels, found {len(all_pids)}"
    assert total_gb < 5.0, f"Memory usage too high: {total_gb:.2f} GB (Gate C limit: 5GB)"


if __name__ == "__main__":
    # If run directly, just execute the test
    pytest.main([__file__, "-s"])
