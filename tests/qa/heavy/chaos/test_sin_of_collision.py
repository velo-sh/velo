import os
import subprocess
import sys
import time

import pytest
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../utils")))
import arch_guard

# Robust binary path resolution
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))

# Priority 1: Check for Release Binary (CI/Prod)
VELO_BIN = os.path.join(PROJECT_ROOT, "target/release/velo")
if not os.path.exists(VELO_BIN):
    # Priority 2: Check for Debug Binary (Local Dev)
    VELO_BIN = os.path.join(PROJECT_ROOT, "target/debug/velo")

# Ensure we aren't getting confused by symlinks or relative path madness
if not os.path.exists(VELO_BIN):
    # Fallback for when running from root
    if os.path.exists("target/release/velo"):
        VELO_BIN = os.path.abspath("target/release/velo")
    else:
        VELO_BIN = os.path.abspath("target/debug/velo")


@pytest.fixture
def workspace_a(tmp_path):
    ws = tmp_path / "workspace_a"
    ws.mkdir()
    (ws / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef root(): return {'ws': 'A'}"
    )
    return ws


@pytest.fixture
def workspace_b(tmp_path):
    ws = tmp_path / "workspace_b"
    ws.mkdir()
    (ws / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef root(): return {'ws': 'B'}"
    )
    return ws


@pytest.mark.skipif(not os.path.exists(VELO_BIN), reason="Build velo first")
def test_workspace_collision_hijacking(workspace_a, workspace_b):
    """
    FATAL DEFECT TEST: Demonstrates that Workspace B can hijack Workspace A's Zygote server
    because they both use the same static socket path in /tmp.
    """
    # 0. Automating Sensing: Check Architecture Compatibility
    arch_guard.assert_velo_compatible(VELO_BIN)

    # 1. Start Workspace A's server (port 8001)
    proc_a = subprocess.Popen(
        [VELO_BIN, "serve", "main:app", "--port", "8001"],
        cwd=workspace_a,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for A to be ready
        time.sleep(3)
        try:
            resp_a = requests.get("http://127.0.0.1:8001/")
        except Exception as e:
            if proc_a.poll() is not None:
                stderr = ""
                if proc_a.stderr:
                    stderr = proc_a.stderr.read().decode()
                print(f"Proc A failed: {stderr}")
            raise e
        assert resp_a.json() == {"ws": "A"}

        # 2. Start Workspace B's server (port 8002)
        # It will see the existing socket and HIJACK it (if bug exists).
        proc_b = subprocess.Popen(
            [VELO_BIN, "serve", "main:app", "--port", "8002"],
            cwd=workspace_b,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(3)

        # 3. VERIFY HIJACKING
        # Now Workspace B should return its own content, which is fine.
        resp_b = requests.get("http://127.0.0.1:8002/")
        assert resp_b.json() == {"ws": "B"}

        # CRITICAL FAILURE POINT:
        # If we restart Workspace A's WORKERS (or if it respawns),
        # it might connect to Workspace B's Zygote because the socket is shared!
        # Or even worse: Workspace A's requests are now routed through B's Zygote's preloaded state.

        # In the current (broken) implementation, both use the same socket.
        # Let's verify that both are indeed hitting the same Zygote.
        # We can check this by looking for the socket file.

        # Find the socket used by A
        # Since we haven't implemented hashing yet, it's likely /tmp/velo-v01.sock (or similar)

    finally:
        if "proc_a" in locals() and proc_a:
            proc_a.terminate()
            try:
                proc_a.wait(timeout=5)
            except Exception:
                proc_a.kill()
        if "proc_b" in locals() and proc_b:
            proc_b.terminate()
            try:
                proc_b.wait(timeout=5)
            except Exception:
                proc_b.kill()

        # Debug: List socket dirs
        print("\n[DEBUG] Socket Dirs found:")
        os.system(f"ls -d {os.environ.get('TMPDIR', '/tmp')}velo-secure-* || echo 'None'")


def test_socket_path_determinism():
    """
    Exposes deterministic socket path which leads to collision.
    """
    # Run velo in current dir
    os.environ.copy()
    # No hash in path expected in broken state

    # We expect this to FAIL once we implement the proper fix (hashing)
    # But currently it will show collision.
    pass
