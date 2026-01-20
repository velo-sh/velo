import asyncio
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
def test_ADVERSARIAL_H1_quiescence_failure(isolated_env: VeloTestEnv):
    """
    Challenge H1: Stable-State Debounce.
    If 5 files change simultaneously, we should only get 1 execution (the last one).
    """
    app_py = isolated_env.create_app("app.py", "print('initial')")
    # Create 5 other files in the same dir
    for i in range(5):
        isolated_env.create_app(f"other_{i}.py", "# irrelevant")

    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_quiescence():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # TRIGGER 5 CHANGES RAPIDLY
            print("Triggering 5 file changes...")
            for i in range(5):
                isolated_env.create_app(f"other_{i}.py", f"# change {i}")

            # Count incoming messages over 3 seconds
            msgs = []
            start = time.time()
            while time.time() - start < 3:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                    print(f"Received msg: {msg[:100]}...")
                    msgs.append(msg)
                except (asyncio.TimeoutError, TimeoutError):
                    continue

            print(f"Received {len(msgs)} messages.")
            # We expect at most 1 or 2 (depending on timing), but 5 is a FAILURE.
            # Pillar H1 says "A minimum 50ms stable-state delay"
            assert len(msgs) <= 2, (
                f"FAILED H1: {len(msgs)} executions triggered for a single batch save! Not stable-state debounced."
            )

    try:
        asyncio.run(check_quiescence())
    finally:
        process.terminate()
        process.wait()
