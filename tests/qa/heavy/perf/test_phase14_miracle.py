import os
import subprocess
import sys
import time
from pathlib import Path


def test_p1_miracle_gateway_hijack(tmp_path):
    """
    Verify Phase 14 P1: Zygote Gateway (execnet Hijacking).
    """
    # First Principles: Derive project root from test file location
    project_root = Path(__file__).resolve().parents[4]

    # Binary discovery: try debug first, then release
    velo_bin = project_root / "target" / "debug" / "velo"
    if not velo_bin.exists():
        velo_bin = project_root / "target" / "release" / "velo"
    if not velo_bin.exists():
        import shutil

        velo_bin = shutil.which("velo")
        if not velo_bin:
            raise RuntimeError("Could not find velo binary")
    velo_bin = str(velo_bin)

    # 1. Start Zygote manually to ensure it's fresh
    subprocess.run([velo_bin, "zygote", "stop"], capture_output=True)

    # 2. Run a simple multi-worker test with --velo
    # We use a dummy test file
    test_file = tmp_path / "dummy_xdist_test.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text("""
import os
import time

def test_worker_identity():
    # Verify we are in a Zygote
    assert os.environ.get("VELO_IS_ZYGOTE") == "1"
    # Verify we have an xdist worker ID
    assert os.environ.get("PYTEST_XDIST_WORKER") is not None
    print(f"Worker {os.environ.get('PYTEST_XDIST_WORKER')} PID: {os.getpid()}")
""")

    # Run with -n 2 --velo
    # We set VELO_DEBUG=1 to see the hijack logs if we added them
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    # RFC-0028: Use the discovered velo_bin directory instead of hardcoded target/debug
    velo_bin_path = Path(velo_bin)
    env["PATH"] = str(velo_bin_path.parent) + os.pathsep + env.get("PATH", "")
    env["VELO_ENV"] = "dev"

    # We also set VELO_ZYGOTE_AUTH to something known to make it easier to trace
    env["VELO_ZYGOTE_AUTH"] = "miracle-secret"

    start_time = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-n", "2", "--velo", "-s"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(project_root),
    )
    end_time = time.perf_counter()
    duration = end_time - start_time

    print(f"Total duration: {duration:.2f}s")
    print(f"STDOUT: {result.stdout}")
    print(f"STDERR: {result.stderr}")

    assert result.returncode == 0

    # Verification of P1: Zygote log should show "Gateway: Handover requested"
    # Use dynamic log path
    try:
        from velo_zygote.paths import VeloPaths

        zygote_log_path = VeloPaths.zygote_log()
    except Exception:
        zygote_log_path = Path.home() / ".local" / "state" / "velo" / "zygote.log"

    if zygote_log_path.exists():
        zygote_log = zygote_log_path.read_text()
        assert "Zygote Gateway: Handover requested" in zygote_log
        assert "Zygote Gateway: Socket handed over to worker" in zygote_log
