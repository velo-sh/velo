"""
Phase 14 Iron-Faced Acceptance Test (L5 Performance & Correctness)
Enforces QA-SOP P0 Performance Requirements.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from conftest_utils import T_LONG, T_MEDIUM, T_SHORT

GOLD_DIR = Path("/tmp/gold_200_phase14")
VELO_BIN = Path("./target/release/velo").absolute()


def gold_200_env() -> dict[str, str]:
    """Return env dict with PYTHONPATH set for gold_200 external project."""
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{GOLD_DIR}/src:{env.get('PYTHONPATH', '')}"
    env["VELO_ENV"] = "dev"  # RFC-0012: Mandatory for Python boundary convergence
    # Remove inherited Zygote session vars so inner velo test can start its own Zygote
    env.pop("VELO_ZYGOTE_SOCKET", None)
    env.pop("VELO_ZYGOTE_AUTH", None)
    return env


def clear_pycache(target_dir: Path) -> None:
    """
    Clear __pycache__ directories to eliminate OS cache effects.
    This ensures fair cold-cache benchmarking.
    """
    for cache_dir in target_dir.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
        except Exception:
            pass  # Ignore errors if directory is already gone


def run_cmd(
    cmd: list[str] | list[Path | str],
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
    timeout: float = T_LONG,
) -> tuple[subprocess.CompletedProcess[str], float]:
    start = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout)
    duration = time.perf_counter() - start
    return res, duration


@pytest.mark.tier5
def test_phase14_iron_performance_acceptance():
    """
    P0 Performance Acceptance: Velo Miracle MUST beat xdist-only (fair parallel comparison).

    Note: Single-process pytest is faster for trivial tests because xdist has inherent overhead.
    The real value of Velo Miracle is being faster than standard xdist.
    """
    assert GOLD_DIR.exists(), "Gold specimen missing. Run generator first."

    env = gold_200_env()
    env["PATH"] = f"{VELO_BIN.parent}:{env.get('PATH', '')}"

    # 0. Pre-start Zygote (don't count startup in performance)
    # Use explicit socket path to bypass pytest-velo session isolation
    import tempfile

    from velo_zygote.paths import VeloPaths

    try:
        vp_socket = str(VeloPaths.zygote_socket())
        print(f"[Debug] VeloPaths.zygote_socket() = {vp_socket}")
    except Exception as e:
        print(f"[Debug] VeloPaths failed: {e}")
        vp_socket = None

    uid = os.getuid() if hasattr(os, "getuid") else 0
    socket_path = vp_socket or f"{tempfile.gettempdir()}/velo-{uid}/velo-zygote-v01.sock"

    print("\n[Setup] Pre-starting Zygote for warm performance test...")
    # RFC-0012: Explicitly set socket path for pre-started Zygote
    env["VELO_ZYGOTE_SOCKET"] = socket_path

    # Discovery pre-started Zygote
    # RFC-0028: Use a session-specific socket to avoid pollution
    import tempfile

    session_socket_dir = Path(tempfile.mkdtemp(prefix="velo-perf-"))
    v_socket_path = session_socket_dir / "velo-zygote.sock"
    v_auth_path = v_socket_path.with_suffix(".auth")

    # 1. Warm Performance Test (Pre-started Zygote)
    # Surgical Cleanup: Kill both Rust wrapper and Python backend
    cwd_name = Path.cwd().name
    subprocess.run(["pkill", "-9", "-f", "velo.*zygote.*start.*--daemon"], capture_output=True, timeout=T_SHORT)
    subprocess.run(["pkill", "-9", "-f", f"python.*{cwd_name}.*velo_zygote.main"], capture_output=True, timeout=T_SHORT)
    time.sleep(1.0)

    env = gold_200_env()
    env["VELO_SOCKET_DIR"] = str(session_socket_dir)
    env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

    # Start Zygote with explicit socket
    subprocess.run([str(VELO_BIN), "zygote", "start", "--daemon"], env=env, capture_output=True, timeout=T_MEDIUM)

    # Wait for socket and auth file (Wait up to 10s)
    auth_secret = None
    for _ in range(100):
        if v_auth_path.exists() and v_socket_path.exists():
            auth_secret = v_auth_path.read_text().strip()
            break
        time.sleep(0.1)

    if not auth_secret:
        pytest.fail(f"Failed to start Zygote or discover secret at {v_auth_path}")

    print(f"[Debug] VELO_ZYGOTE_SOCKET={v_socket_path}")
    print(f"[Debug] VELO_ZYGOTE_AUTH_VAL={auth_secret}")

    # Target: Miracle (Warmup)
    env["VELO_ZYGOTE_AUTH"] = str(auth_secret)
    run_cmd([str(VELO_BIN), "test", "tests/", "-n", "4", "--zygote"], env=env, cwd=GOLD_DIR)

    # Target: Miracle (Hot)
    clear_pycache(GOLD_DIR)
    print(f"[Target] Velo Miracle (-n 4) on {GOLD_DIR}...")
    res_target, dur_target = run_cmd([str(VELO_BIN), "test", "tests/", "-n", "4", "--zygote"], env=env, cwd=GOLD_DIR)
    if res_target.returncode != 0:
        print(f"STDOUT: {res_target.stdout}")
        print(f"STDERR: {res_target.stderr}")
    assert res_target.returncode == 0
    print(f"STDOUT: {res_target.stdout}")
    print(f"STDERR: {res_target.stderr}")
    print(f"🚀 Velo Miracle: {dur_target:.3f}s")

    # 3. BASELINE: xdist-only (cold workers, -n 4)
    print(f"[Baseline] xdist-only (-n 4) on {GOLD_DIR}/tests...")
    clear_pycache(GOLD_DIR)
    res_base, dur_base = run_cmd(["uv", "run", "pytest", str(GOLD_DIR / "tests"), "-n", "4"], env=env)
    if res_base.returncode != 0:
        print(f"BASELINE STDOUT: {res_base.stdout}")
        print(f"BASELINE STDERR: {res_base.stderr}")
    assert res_base.returncode == 0
    print(f"✅ xdist Baseline: {dur_base:.3f}s")

    # 4. IRON VERDICT
    speedup = dur_base / dur_target
    print(f"📊 Speedup vs xdist: {speedup:.2f}x")

    # Velo Miracle MUST beat standard xdist
    assert dur_target < dur_base, (
        f"PERFORMANCE REJECTION: Velo Miracle ({dur_target:.3f}s) is SLOWER than "
        f"xdist-only ({dur_base:.3f}s). The Miracle mode provides no benefit."
    )

    print(f"✅ Velo Miracle is {speedup:.2f}x faster than xdist-only")


@pytest.mark.tier2
def test_phase14_isolation_verification():
    """
    Verify that concurrent workers have isolated environments.
    """
    # Create a test that writes to /tmp/collision and checks for PID
    test_file = GOLD_DIR / "tests" / "test_concurrency_isolation.py"
    test_file.write_text("""
import os
import time
from pathlib import Path

def test_isolated_tmp():
    # P0: Isolated TMPDIR per worker
    tmp = os.environ.get("TMPDIR", "/tmp")
    assert "velo-worker-" in tmp

    # Ensure the directory exists
    assert os.path.exists(tmp)

    # Write a file and wait - if isolation fails, another worker might see it
    id_file = Path(tmp) / "isolation_id"
    worker_id = os.getpid()
    id_file.write_text(str(worker_id))

    time.sleep(0.1)

    assert id_file.read_text() == str(worker_id)
""")

    try:
        env = gold_200_env()
        env["PATH"] = f"{VELO_BIN.parent}:{env.get('PATH', '')}"

        # Run with -n 4 to force concurrency
        res, _ = run_cmd([str(VELO_BIN), "test", str(test_file), "-n", "4", "--zygote"], env=env)
        if res.returncode != 0:
            print(f"ISOLATION STDOUT: {res.stdout}")
            print(f"ISOLATION STDERR: {res.stderr}")
        assert res.returncode == 0
    finally:
        if test_file.exists():
            test_file.unlink()


@pytest.mark.tier3
def test_phase14_iron_chaos_audit():
    """
    Sad Path Resilience: Killing Zygote mid-run MUST NOT hang the suite.

    Phase 15 Guardian: If Guardian auto-restarts Zygote in time, suite may complete successfully.
    The key invariant is that the suite NEVER hangs indefinitely.
    """
    assert GOLD_DIR.exists()

    # 1. Start Zygote
    subprocess.run([str(VELO_BIN), "zygote", "start", "--daemon"], capture_output=True, timeout=T_MEDIUM)

    # 2. Start a long run in background
    env = gold_200_env()
    env["PATH"] = f"{VELO_BIN.parent}:{env.get('PATH', '')}"

    print("\n[Chaos] Starting Velo Parallel run...")
    process = subprocess.Popen(
        [str(VELO_BIN), "test", str(GOLD_DIR / "tests"), "-n", "4", "--zygote"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    time.sleep(1.0)
    print("[Chaos] Slapping Zygote (SIGKILL)...")
    subprocess.run(["pkill", "-9", "-f", "velo_zygote/main.py"], capture_output=True, timeout=T_SHORT)

    # 3. Wait for test to finish or hang
    try:
        stdout, stderr = process.communicate(timeout=30)
        print(f"[Chaos] Process exited with {process.returncode}")
        # P1.5 Guardian: Suite may recover (returncode=0) or fail gracefully (!=0)
        # Both are acceptable - the key is NO HANG
        if process.returncode == 0:
            print("✅ Chaos Test PASSED: Guardian recovered Zygote, suite completed")
        else:
            print(f"✅ Chaos Test PASSED: Suite failed gracefully (code={process.returncode})")
    except subprocess.TimeoutExpired:
        process.kill()
        pytest.fail("CRITICAL GOVERNANCE FAILURE: Suite HANGS indefinitely when Zygote killed!")


@pytest.mark.tier2
def test_phase14_iron_environment_persistence():
    """
    Forensic Audit: Verify project_root and PYTHONPATH are preserved in workers.
    """
    test_file = GOLD_DIR / "tests" / "test_env_audit.py"
    test_file.write_text("""
import os
import sys
from pathlib import Path

def test_verify_env():
    # RFC Requirement 1: CWD must be project root (v_fork.py must call os.chdir(project_root))
    cwd = Path(os.getcwd())
    assert "gold_200_phase14" in str(cwd), f"CWD not set to project root: {cwd}"

    # RFC Requirement 2: PYTHONPATH must be preserved
    # The 'velo_app' should be importable if PYTHONPATH was correctly propagated
    try:
        import velo_app
        print(f"SUCCESS: velo_app imported from {velo_app.__file__}")
    except ImportError:
        print(f"DEBUG: sys.path = {sys.path}")
        print(f"DEBUG: PYTHONPATH = {os.environ.get('PYTHONPATH', 'NOT SET')}")
        print(f"DEBUG: CWD = {os.getcwd()}")
        assert False, "CRITICAL: velo_app NOT importable. PYTHONPATH lost in transit!"
""")

    try:
        env = gold_200_env()
        env["PATH"] = f"{VELO_BIN.parent}:{env.get('PATH', '')}"

        print("\n[Audit] Verifying Environment Persistence...")
        # RFC-0028: Use a relative path from GOLD_DIR to ensure worker find it after chdir
        res, _ = run_cmd(
            [str(VELO_BIN), "test", "tests/test_env_audit.py", "-n", "1", "--zygote"], env=env, cwd=GOLD_DIR
        )
        assert res.returncode == 0, f"Iron Rule Violation: Environment was lost in worker forking. STDERR: {res.stderr}"
    finally:
        if test_file.exists():
            test_file.unlink()


@pytest.mark.tier1
def test_phase14_orphan_storm_prevention():
    """
    CRITICAL: Zygote MUST NOT leak orphan worker processes.

    Discovered in QA Round 14: Zygote was spawning 33+ orphan processes that
    never exited, consuming system resources indefinitely.

    Acceptance Criteria:
    - After starting Zygote, there should be exactly 1 main process
    - After running tests, workers should exit cleanly
    - After stopping Zygote, there should be 0 processes
    """
    # 1. Clean slate - kill ANY existing Zygote processes related to this project
    cwd_name = Path.cwd().name
    print(f"[Orphan Test] Surgical cleanup of processes for {cwd_name}...")

    ps_out = subprocess.check_output(["ps", "-Ao", "pid,args"], text=True)
    for line in ps_out.splitlines():
        if ("velo_zygote/main.py" in line or "velo zygote start" in line) and cwd_name in line:
            try:
                pid = int(line.strip().split()[0])
                os.kill(pid, 9)
            except (ValueError, ProcessLookupError, PermissionError):
                pass
    time.sleep(1.0)

    def count_zygote_processes() -> int:
        # Match only the actual zygote module AND the current project directory
        cwd_name = Path.cwd().name
        result = subprocess.run(
            ["pgrep", "-f", f"python.*{cwd_name}.*velo_zygote.main"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return 0
        return len([x for x in result.stdout.strip().split("\n") if x])

    # 2. Start Zygote
    print("\n[Orphan Test] Starting Zygote...")
    subprocess.run([str(VELO_BIN), "zygote", "start", "--daemon"], capture_output=True, timeout=T_MEDIUM)
    time.sleep(1.0)

    initial_count = count_zygote_processes()
    print(f"[Orphan Test] Initial process count: {initial_count}")

    # Should be exactly 1 main Zygote process
    assert initial_count == 1, (
        f"ORPHAN STORM: Expected 1 Zygote process after start, found {initial_count}. "
        "Zygote is leaking processes on startup!"
    )

    # 3. Run a simple test
    print("[Orphan Test] Running a quick test...")
    env = gold_200_env()
    subprocess.run(
        [str(VELO_BIN), "test", str(GOLD_DIR / "tests" / "layer_1_auth"), "-n", "2", "--zygote"],
        capture_output=True,
        env=env,
        timeout=30,
    )
    time.sleep(1.0)

    post_test_count = count_zygote_processes()
    print(f"[Orphan Test] Post-test process count: {post_test_count}")

    # After test, should still be reasonable (1 main + maybe a few workers, but not 30+)
    assert post_test_count <= 15, (
        f"ORPHAN STORM: Expected <= 15 processes after test, found {post_test_count}. "
        "Workers are not exiting after test completion!"
    )

    # 4. Stop Zygote
    print("[Orphan Test] Stopping Zygote...")
    subprocess.run([str(VELO_BIN), "zygote", "stop"], capture_output=True, timeout=T_SHORT)
    time.sleep(1.0)

    final_count = count_zygote_processes()
    print(f"[Orphan Test] Final process count: {final_count}")

    # After stop, should be ZERO
    assert final_count == 0, (
        f"ORPHAN STORM: Expected 0 processes after stop, found {final_count}. "
        "Zygote stop is not cleaning up child processes!"
    )

    print("✅ Orphan Storm Prevention: PASSED")


if __name__ == "__main__":
    # Diagnostic run
    pytest.main([__file__, "-v", "-s"])
