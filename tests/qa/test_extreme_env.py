import asyncio
import json
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
def test_EXTREME_SINCERITY_env_drift(isolated_env: VeloTestEnv):
    """
    Challenge: Environment Drift.
    If I modify a .env file, do new forks pick up the new values?
    """
    # Create initial .env
    isolated_env.create_app(".env", "VIBE_VAR=initial")

    code = """
import os
print(f"VIBE_VAR={os.getenv('VIBE_VAR', 'NONE')}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    # Start Vibe
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_drift():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Step 1: Verify initial
            msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            assert "VIBE_VAR=initial" in json.loads(msg).get("output", "")

            # Step 2: Modify .env
            print("Modifying .env while Vibe is running...")
            isolated_env.create_app(".env", "VIBE_VAR=drifted")

            # Step 3: Trigger rerun
            isolated_env.create_app("app.py", code)

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")
            print(f"Captured output: {repr(output)}")

            # ASSERTION: If it says 'initial', it's a 'Toy' engine.
            if "VIBE_VAR=initial" in output:
                print("!!! AUDIT FINDING: Environment Drift ignored. Zygote is stale.")
                pytest.fail("Environment Drift: Vibe failed to propagate .env changes to forks.")

            assert "VIBE_VAR=drifted" in output

    try:
        asyncio.run(check_drift())
    finally:
        process.terminate()
        process.wait()
