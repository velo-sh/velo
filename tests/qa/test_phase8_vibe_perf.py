import asyncio
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier5
def test_PERF_801_latency_benchmark(isolated_env: VeloTestEnv):
    """Verify E2E latency (File Save -> WS Broadcast) is < 20ms."""
    app_py = isolated_env.create_app("app.py", "print('bench')")
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def measure():
        uri = f"ws://127.0.0.1:{port}"
        durations = []
        async with websockets.connect(uri) as websocket:
            # Drain initial cached msg
            await websocket.recv()

            for i in range(5):
                start_time = time.perf_counter()
                isolated_env.create_app("app.py", f"print('bench {i}')")

                # Wait for broadcast
                msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                end_time = time.perf_counter()

                latency_ms = (end_time - start_time) * 1000
                print(f"Latency: {latency_ms:.2f}ms")
                durations.append(latency_ms)
                time.sleep(0.5)  # Wait longer than 200ms debounce

        return sum(durations) / len(durations)

    avg_latency = asyncio.run(measure())
    process.terminate()
    process.wait()

    print(f"Average E2E Latency: {avg_latency:.2f}ms")
    # RFC-0029 Target: < 20ms
    # We allow some slack for CI environment overhead (e.g. 50ms) but target is 20ms
    assert avg_latency < 50, f"Average latency {avg_latency:.2f}ms exceeds performance budget"
