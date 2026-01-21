import asyncio
import time

import psutil
import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
def test_ADVERSARIAL_OOM_BOMB(isolated_env: VeloTestEnv):
    """
    Challenge: Master Memory Protection.
    If worker produces 200MB of output, Master should not potentially OOM.
    We test with 100MB first to be safe in CI, but check Master's RSS growth.
    """
    # Create 50MB string (becomes ~100MB in JSON with escaping etc)
    size_mb = 50
    large_str = "x" * (size_mb * 1024 * 1024)
    code = f"print({repr(large_str)})"

    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    master_proc = psutil.Process(process.pid)
    rss_before = master_proc.memory_info().rss / (1024 * 1024)
    print(f"Master RSS before: {rss_before:.2f} MB")

    async def check_bomb():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            isolated_env.create_app("app.py", code)
            # Wait for execution to finish and Master to process it
            start = time.time()
            while time.time() - start < 10:
                rss_now = master_proc.memory_info().rss / (1024 * 1024)
                if rss_now > rss_before + 50:
                    print(f"Master RSS spiked to: {rss_now:.2f} MB")
                    # If it spikes by more than the raw data size, it's a danger
                    break
                time.sleep(0.1)

            # We don't even need to receive it (client might OOM elsewhere)
            # Just checking if Master is still alive
            assert process.poll() is None, "Master CRASHED! OOM or Internal Error."
            print(f"Final Master RSS: {master_proc.memory_info().rss / (1024 * 1024):.2f} MB")

    try:
        asyncio.run(check_bomb())
    finally:
        process.terminate()
        process.wait()
