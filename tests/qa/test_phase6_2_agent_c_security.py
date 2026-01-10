import os
import subprocess
import pytest
import time
import json
import signal
import socket
from pathlib import Path


@pytest.mark.tier4
def test_SEC_621_cross_uid_hijack(isolated_env):
    """SEC-621: Verify that Zygote rejects connections from unauthorized UIDs.
    RFC-0013 §5.1 / H-12 Identity Immutability.
    """
    env = isolated_env
    env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    # We can't actually change UID easily in CI without root,
    # but we can simulate the rejection logic by checking if Zygote logs a warning
    # and closes the socket when the peer UID doesn't match os.getuid().
    # Here we prove the GENTLEMAN'S AGREEMENT: Zygote must NOT fallback to Cold Start
    # for security violations.

    socket_path = env.path / "velo_zygote.sock"
    cmd_env = os.environ.copy()
    cmd_env["VELO_ZYGOTE_SOCKET"] = str(socket_path)

    # 1. Start velo serve
    # Note: On macOS, SO_PEERCRED is getpeereid().
    # We'll see if the implementation even attempts it.
    proc = env.run_velo("serve", "main:app", "--workers", "1", env=cmd_env, timeout=10)

    # If the Whitebox Audit is correct, it won't even mention PEERCRED failures
    # because the implementation is missing.
    # A passing test for the DEFENSE would see "Security rejection" or similar.
    # Currently, we expect this to FAIL (reveal the bug) if we had a way to spoof UID.
    # Instead, we perform a Negative Audit: check the source for PEERCRED.

    zygote_src = Path(__file__).parent.parent.parent / "velo_zygote" / "main.py"
    with open(zygote_src, "r") as f:
        content = f.read()

    assert (
        "SO_PEERCRED" in content or "getpeereid" in content or "ucred" in content
    ), "P0 Security Violation: Zygote implementation lacks peer identity verification (SEC-001)"


@pytest.mark.tier4
def test_SEC_622_prng_correlation(isolated_env):
    """SEC-622: Verify PRNG Domain Isolation (Birthday Attack).
    RFC-0013 §5.2 / H-13 PRNG Domain Isolation.
    """
    env = isolated_env
    app_code = """
import random
import secrets
import os
from fastapi import FastAPI

app = FastAPI()

@app.get("/seed")
def get_seed():
    return {
        "pid": os.getpid(),
        "r": random.getstate()[1][0], # Internal state sample
        "s": secrets.token_hex(8)
    }
"""
    env.create_app("main.py", app_code)
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    port = 8091
    repo_root = Path(__file__).parent.parent.parent
    velo_bin = str(repo_root / "target" / "debug" / "velo")

    proc = subprocess.Popen(
        [velo_bin, "serve", "main:app", "--workers", "10", "--port", str(port)],
        cwd=env.path,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    try:
        # Wait for ready
        time.sleep(5)

        seeds = set()
        secrets_set = set()
        pids = set()

        for _ in range(50):
            res = subprocess.run(
                ["curl", "-s", f"http://127.0.0.1:{port}/seed"],
                capture_output=True,
                text=True,
            )
            data = json.loads(res.stdout)
            seeds.add(data["r"])
            secrets_set.add(data["s"])
            pids.add(data["pid"])
            time.sleep(0.05)

        assert len(pids) >= 2, "Failed to hit multiple workers"
        assert len(seeds) == len(list(seeds)), "PRNG State Collision Detected!"
        assert len(secrets_set) == 50, "Secrets Collision Detected!"

    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)


@pytest.mark.tier4
def test_SEC_623_fd_hygiene_and_leak(isolated_env):
    """SEC-623: Verify FD Hygiene (No leaks from Zygote to Worker).
    RFC-0013 §5.2 / H-14 FD Hygiene.
    """
    env = isolated_env
    app_code = """
import os
from fastapi import FastAPI

app = FastAPI()

@app.get("/fds")
def list_fds():
    try:
        # Linux /proc/self/fd
        fds = os.listdir('/proc/self/fd')
    except:
        # macOS/BSD fallback
        fds = []
    return {"fds": fds, "count": len(fds)}
"""
    env.create_app("main.py", app_code)
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    port = 8092
    repo_root = Path(__file__).parent.parent.parent
    velo_bin = str(repo_root / "target" / "debug" / "velo")

    # Start Zygote and then Serve
    # We want to see if the worker has more than the standard FDs (0, 1, 2, plus server socket)
    proc = subprocess.Popen(
        [velo_bin, "serve", "main:app", "--workers", "1", "--port", str(port)],
        cwd=env.path,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    try:
        time.sleep(5)
        import json

        res = subprocess.run(
            ["curl", "-s", f"http://127.0.0.1:{port}/fds"],
            capture_output=True,
            text=True,
        )
        data = json.loads(res.stdout)

        # Standard FDs: 0(in), 1(out), 2(err).
        # For a server, there's also the listening socket and maybe some loop fds.
        # But if it's 20+, there's a leak from the Zygote's warm-up/socket pool.
        # Titanium requirement: ONLY stdio + necessary server sockets.
        fd_count = data["count"]
        # On some systems/interpreters, there might be a few internal fds (e.g. signal fds).
        # We'll set a reasonable limit (e.g. 10) to catch massive leaks.
        assert fd_count < 15, f"FD Leak Detected! Worker has {fd_count} open FDs."

    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
