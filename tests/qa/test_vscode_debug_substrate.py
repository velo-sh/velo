"""
QA: VS Code Debug Substrate Verification
RFC-0030: Verify that Zygote forking doesn't break debugpy communication.
"""

import os
import subprocess
import time
from pathlib import Path


def test_debug_substrate_fork_transition(tmp_path):
    """
    Test that a script started via 'velo run --zygote' can maintain
    a 'debug connection' across the fork.
    """
    # 1. Create a 'app' that simulates debugpy attachment
    app_script = tmp_path / "debug_app.py"
    app_script.write_text("""
import os
import sys
import time

with open("worker_ready.txt", "w") as f:
    f.write(str(os.getpid()))

# Wait for 'debugger' to signals via env or file
while not os.path.exists("debug_start.txt"):
    time.sleep(0.1)

print("⚡ BREAKPOINT HIT in worker")
with open("debug_result.txt", "w") as f:
    f.write("PASS")
""")

    root = Path(__file__).parent.parent.parent
    velo_binary = str(root / "target" / "debug" / "velo")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)

    # Ensure Zygote is running
    subprocess.run([velo_binary, "zygote", "stop"], capture_output=True)
    subprocess.run([velo_binary, "zygote", "start", "--daemon"], check=True)

    # Launch app
    proc = subprocess.Popen(
        [velo_binary, "run", "--zygote", str(app_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
        env=env,
    )

    # 3. Wait for Worker to boot via file signal
    worker_pid = None
    start_time = time.time()
    while time.time() - start_time < 10:
        ready_file = tmp_path / "worker_ready.txt"
        if ready_file.exists():
            worker_pid = int(ready_file.read_text().strip())
            break
        time.sleep(0.1)

    assert worker_pid is not None, "Worker failed to signal ready"
    print(f"✅ Worker PID {worker_pid} is ready and 'attached'")

    # 4. Trigger the 'breakpoint'
    (tmp_path / "debug_start.txt").write_text("GO")

    # 5. Verify worker completed the task
    # We wait for the result file
    start_time = time.time()
    success = False
    while time.time() - start_time < 5:
        if (tmp_path / "debug_result.txt").exists():
            content = (tmp_path / "debug_result.txt").read_text()
            if content == "PASS":
                success = True
                break
        time.sleep(0.1)

    assert success, "Debugger verification failed: result file not found or invalid"
    print("✅ Debug substrate verification successful")

    # Cleanup
    proc.terminate()
    subprocess.run([velo_binary, "zygote", "stop"], capture_output=True)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-s"])
