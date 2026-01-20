import asyncio
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
def test_EXTREME_SINCERITY_side_effect_pollution(isolated_env: VeloTestEnv):
    """
    Challenge: Side-Effect Pollution.
    If 5 files change, Vibe triggers 5-6 forks.
    If each fork appends to a log, we get 6 entries for 1 conceptual save.
    """
    log_file = isolated_env.path / "audit.log"
    code = f"""
with open({repr(str(log_file))}, 'a') as f:
    f.write('EXEC\\n')
print('Logged')
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    # Start Vibe
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_pollution():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Step 1: Initial Log
            await asyncio.wait_for(websocket.recv(), timeout=2.0)

            # Step 2: Trigger "Conceptually Single" save with 5 file changes
            print("Triggering conceptual 'Save All' (5 files)...")
            for i in range(5):
                isolated_env.create_app(f"trigger_{i}.py", f"# {i}")

            # Wait for storms to settle
            time.sleep(3)

            with open(log_file) as f:
                lines = f.readlines()
                count = len(lines)
                print(f"Total log entries: {count}")

            # ASSERTION:conceptually 1 save (+1 initial) = 2 entries.
            # Anything > 3 is a POLLUTION failure due to lack of Quiescence.
            assert count <= 3, f"FAILED: Side-effect pollution detected! Found {count} entries for 1 batch save."

    try:
        asyncio.run(check_pollution())
    finally:
        process.terminate()
        process.wait()
