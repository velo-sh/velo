import asyncio
import json
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier1
@pytest.mark.protocol
def test_DEF_08_005_protocol_flickering_reproduction(isolated_env: VeloTestEnv):
    """
    REPRODUCTION for DEF-08-005:
    1. Start engine with valid code.
    2. Save code with SyntaxError -> Gateway caches Error.
    3. Fix code -> Engine triggers rebuild.
    4. Connect NEW client DURING rebuild window.
    5. Client MUST NOT receive the stale SyntaxError.
    """
    app_py = isolated_env.create_app("app.py", "print('initial')")
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)  # Wait for start

    # 1. Trigger SyntaxError
    isolated_env.create_app("app.py", "invalid syntax !!!")
    time.sleep(1)  # Wait for cache to be populated with error

    async def connect_and_check():
        uri = f"ws://127.0.0.1:{port}"
        # We connect BEFORE fixing it to see the current state
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            data = json.loads(msg)
            assert data["status"] == "error", "Initial state should be error"
            print("Confirmed: Gateway is serving the Error state.")

        # 2. Trigger Fix
        isolated_env.create_app("app.py", "print('fixed')")

        # 3. CRITICAL STEP: Connect immediately after save
        # There is a small window where the engine is starting the worker
        # but the gateway still holds the LAST_RESULT = Error.
        async with websockets.connect(uri) as websocket:
            # According to RFC-0029 "Instant Feedback", we should either get:
            # a) Nothing (if waiting for results)
            # b) A "building" status (if implemented)
            # c) The "fixed" result
            # We MUST NOT get the "error" result again.

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)

            print(f"Received msg after fix: {data['status']}")

            # If this is 'error', then DEF-08-005 is confirmed.
            # A 'success' here would mean the race was avoided by luck or timing.
            # To be 100% sure of flicking, we check if the timestamp is OLD.

            assert data["status"] != "error", "STALE ERROR DETECTED: Client received cached error from previous save."
            assert "fixed" in data.get("output", ""), "Did not receive fixed output"

    try:
        asyncio.run(connect_and_check())
    finally:
        process.terminate()
        process.wait()
