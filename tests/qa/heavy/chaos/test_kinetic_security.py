import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest


@pytest.mark.tier1
def test_kinetic_prng_re_randomization(isolated_env):
    """RFC-0013 §5.2: Verify PRNG re-seeding after fork."""
    env = isolated_env
    # App that returns random state
    app_code = """
import random
import secrets
import os
from fastapi import FastAPI

app = FastAPI()

@app.get("/random")
def get_random():
    return {
        "pid": os.getpid(),
        "random": random.random(),
        "secrets": secrets.token_hex(16)
    }
"""
    env.create_app("main.py", app_code)
    # MANDATORY: Add pyproject.toml so Velo detects FastAPI and enables Zygote
    (env.path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')

    # Start velo serve in background
    port = 8087
    repo_root = Path(__file__).parents[4]
    velo_bin = str(repo_root / "target" / "release" / "velo")
    if not os.path.exists(velo_bin):
        velo_bin = str(repo_root / "target" / "debug" / "velo")

    cmd = [
        velo_bin,
        "serve",
        "main:app",
        "--workers",
        "4",
        "--port",
        str(port),
        "--host",
        "127.0.0.1",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=env.path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid,
    )

    try:
        # Wait for "All workers ready"
        start_time = time.time()
        ready = False
        while time.time() - start_time < 20:
            import select

            r, _, _ = select.select([proc.stderr], [], [], 0.5)
            if r:
                line = proc.stderr.readline()
                if "All workers ready" in line or "Uvicorn running on" in line:
                    ready = True
                    break

        if not ready:
            pytest.fail("Server failed to start within 20s")

        # Collect random numbers from different workers
        samples = {}
        for _ in range(30):
            try:
                res = subprocess.run(
                    ["curl", "-s", f"http://127.0.0.1:{port}/random"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                data = json.loads(res.stdout)
                pid = data["pid"]
                if pid not in samples:
                    samples[pid] = []
                samples[pid].append(data)
            except:
                pass
            time.sleep(0.1)

        # 1. Verify we hit multiple workers
        assert len(samples) >= 2, f"Only hit {len(samples)} workers, need at least 2 for comparison"

        # 2. Verify uniqueness across workers
        all_randoms = [s["random"] for p in samples for s in samples[p]]
        assert len(set(all_randoms)) == len(all_randoms), "Detected duplicate random values across workers!"

        all_secrets = [s["secrets"] for p in samples for s in samples[p]]
        assert len(set(all_secrets)) == len(all_secrets), "Detected duplicate secrets across workers!"

    finally:
        # Cleanup
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except:
            pass
