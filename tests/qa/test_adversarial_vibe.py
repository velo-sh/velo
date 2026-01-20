import asyncio
import json
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
@pytest.mark.adversarial
def test_ADVERSARIAL_G1_native_leak(isolated_env: VeloTestEnv):
    """
    Challenge G1: Capturing stdout.
    If code writes directly to FD 1 (libc level), does Vibe capture it?
    """
    code = """
import os
import sys
print('Python output')
os.write(1, b'Native output\\n')
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_leak():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Re-trigger save
            isolated_env.create_app("app.py", code)
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")
            print(f"Captured output: {repr(output)}")

            # ASSERTION: Must capture BOTH
            assert "Python output" in output
            assert "Native output" in output, "FAILED G1: Native FD 1 writes bypassed the execution capture!"

    try:
        asyncio.run(check_leak())
    finally:
        process.terminate()
        process.wait()
