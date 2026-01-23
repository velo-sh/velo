import asyncio
import json
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
@pytest.mark.adversarial
def test_ADVERSARIAL_PIPE_DEADLOCK(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: Pipe capacity.
    Standard pipes are 64KB. If worker writes 1MB, it should NOT hang.
    """
    # Create a 2MB string
    large_str = "x" * (2 * 1024 * 1024)
    code = f"print('{large_str}')"

    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_deadlock() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Re-trigger save
            isolated_env.create_app("app.py", code)

            # If it deadlocks, this will timeout
            print("Waiting for 2MB message...")
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(msg)
                output = data.get("output", "")
                print(f"Captured output length: {len(output)}")
                assert len(output) >= 2 * 1024 * 1024
            except TimeoutError:
                pytest.fail("Velo Deadlocked! Worker blocked on pipe write > 64KB.")

    try:
        asyncio.run(check_deadlock())
    finally:
        process.terminate()
        process.wait()
