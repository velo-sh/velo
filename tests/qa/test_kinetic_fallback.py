import os
import subprocess
import time
from pathlib import Path

import pytest

VELO_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../target/debug/velo"))


@pytest.mark.skipif(not os.path.exists(VELO_BIN), reason="Binary missing")
def test_kinetic_silent_fallback_on_corrupt_zygote(tmp_path):
    """
    KINETIC-001: Verification of Silent Fallback invariant.
    If Zygote socket dir is blocked by a file, velo serve MUST fall back to cold start.
    """
    # 1. Create a dummy project
    project_dir = tmp_path / "dummy_app"
    project_dir.mkdir()
    (project_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef read_root(): return {'Hello': 'World'}"
    )

    # 2. Simulate a "Shadow Trap" / Corrupt Zygote
    # Create the base socket dir as a FILE to force failure in get_socket_dir or connection
    socket_base = Path(f"/tmp/velo-{os.getuid()}")
    if socket_base.exists():
        if socket_base.is_dir():
            import shutil

            shutil.rmtree(socket_base)
        else:
            socket_base.unlink()

    socket_base.touch()  # Create a FILE where a DIR should be

    # 3. Run velo serve
    proc = subprocess.Popen(
        [VELO_BIN, "serve", "main:app", "--port", "8081"],
        cwd=project_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Give it time to fall back and reach cold start
        # On this machine, cold start might crash due to architecture mismatch,
        # but that proves we reached it!
        time.sleep(5)

        # Terminate to get output
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)

        print(f"STDERR SUMMARY:\n{stderr[:1000]}")
        assert "KINETIC_FALLBACK" in stderr, "Fallback marker 'KINETIC_FALLBACK' not found in stderr!"

    finally:
        if socket_base.exists():
            socket_base.unlink()
