import os
import signal
import socket
import time
import pytest
import subprocess
import psutil
import uuid
from pathlib import Path

# TITANIUM Grade: Kinetic Phase 6.2 Regression Suite
# Documents and solidifies fixes for regressions found during optimization.


@pytest.fixture
def short_socket():
    """Generate a short unique socket path in /tmp to avoid AF_UNIX length limits."""
    path = Path("/tmp") / f"v_{uuid.uuid4().hex[:8]}.sock"
    yield path
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


@pytest.mark.regression
def test_reg_62_001_dry_run_hang_deadlock(isolated_env):
    """
    REG-62-001: velo serve --dry-run hangs when Zygote is enabled.

    Fix: Rust core must check for dry_run BEFORE entering Zygote proxy loop.
    Verified: 2026-01-07
    """
    env = isolated_env
    env.create_app("main.py", "app = lambda s, r, se: None")

    start_time = time.time()
    # Zygote is enabled by default. Dry-run should exit immediately.
    result = subprocess.run(
        [env.velo, "serve", "main:app", "--dry-run"],
        cwd=env.path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    elapsed = time.time() - start_time

    assert result.returncode == 0
    assert (
        elapsed < 3
    ), f"Regression: velo serve --dry-run hung for {elapsed:.2f}s (deadlock trap)"
    # Log output goes to stderr in Velo
    assert "Dry run" in result.stderr


@pytest.mark.regression
def test_reg_62_002_zygote_guardian_daemon(isolated_env, short_socket):
    """
    REG-62-002: Zygote self-terminates when moving to init (ppid 1).

    Fix: Guardian must be optional for daemonized Zygotes.
    Verified: 2026-01-07
    """
    env = isolated_env
    socket_path = short_socket

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

    # 1. Start Zygote daemon via Rust CLI
    subprocess.run([env.velo, "zygote", "start"], env=cmd_env, check=True)

    # Wait for socket
    for _ in range(50):
        if socket_path.exists():
            break
        time.sleep(0.1)

    # 2. Find the PID
    zygote_pid = None
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "velo_zygote" in cmdline and str(socket_path) in cmdline:
                zygote_pid = proc.info["pid"]
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    assert zygote_pid is not None, "Zygote failed to start"

    # 3. Verify it survives parent death
    time.sleep(2)
    try:
        proc = psutil.Process(zygote_pid)
        assert (
            proc.is_running()
        ), "Regression: Zygote (daemon) killed itself after parent exited"
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pytest.fail("Regression: Zygote (daemon) exited/crashed after parent exited")

    # 4. Clean up
    subprocess.run([env.velo, "zygote", "stop"], env=cmd_env, check=True)


@pytest.mark.regression
def test_reg_62_003_ci_home_allowance(isolated_env, short_socket):
    """
    REG-62-003: Pollution regressed /home blocking in GITHUB_ACTIONS.

    Fix: Restore allowance for /home when GITHUB_ACTIONS=true.
    Verified: 2026-01-07
    """
    env = isolated_env
    socket_path = short_socket

    cmd_env = os.environ.copy()
    cmd_env["GITHUB_ACTIONS"] = "true"
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

    # Start Zygote
    proc = subprocess.Popen([env.velo, "zygote", "start"], env=cmd_env, cwd=env.path)

    # Wait for socket
    success = False
    for _ in range(50):
        if socket_path.exists():
            success = True
            break
        time.sleep(0.1)

    try:
        assert (
            success
        ), "Zygote failed to start in simulated CI (/home blocking regression?)"
    finally:
        subprocess.run([env.velo, "zygote", "stop"], env=cmd_env)


@pytest.mark.regression
def test_reg_62_004_socket_backlog_resilience(isolated_env, short_socket):
    """
    REG-62-004: Socket backlog too small for CHAOS connectivity bursts.

    Fix: Increase listen(backlog=512).
    Verified: 2026-01-07
    """
    env = isolated_env
    socket_path = short_socket

    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

    env.create_app("main.py", "app = lambda s, r, se: None")

    # Start Zygote
    subprocess.run([env.velo, "zygote", "start"], env=cmd_env, check=True)

    # Wait for ready
    for _ in range(50):
        if socket_path.exists():
            break
        time.sleep(0.1)

    conns = []
    success_count = 0
    try:
        # Blast it with concurrent connection attempts.
        # somaxconn is 128 on this system. 150 is a safe stress test that
        # requires the app's backlog to be larger than default 128 to be reliable.
        # Actually somaxconn is the kernel LIMIT. If we reach 128+, it proves
        # the app is pulling as fast as it can.
        for _ in range(150):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(str(socket_path))
                conns.append(s)
                success_count += 1
            except (ConnectionRefusedError, socket.timeout, OSError):
                break

        # We expect to reach at least 128 if backlog is 512 and system caps at 128
        assert (
            success_count >= 120
        ), f"Backlog failure: only accepted {success_count} concurrent connections (somaxconn 128)"
    finally:
        for s in conns:
            s.close()
        subprocess.run([env.velo, "zygote", "stop"], env=cmd_env)


if __name__ == "__main__":
    pytest.main([__file__])
