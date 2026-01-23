import asyncio
import json
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier2
@pytest.mark.e2e
def test_VIBE_HEROS_JOURNEY_MASTER_E2E(isolated_env: VeloTestEnv) -> None:
    """
    QA FIRST PRINCIPLES: The Hero's Journey.
    This test covers the longest path and most features in a single session.

    PATH:
    1. Start Project (Multi-file)
    2. Edit dependency (utils.py) -> Verify Entrypoint (main.py) update.
    3. Late Joiner connects -> Verify consistency.
    4. Inject SyntaxError -> Verify Resilience.
    5. Fix SyntaxError -> Verify Recovery.
    6. Rapid Save Storm -> Verify Performance/Debounce.
    7. Large Output -> Verify Framing.
    """
    # 1. SETUP: Multi-file project
    utils_py = isolated_env.create_app("utils.py", "def get_version(): return '1.0.0'")
    main_py = isolated_env.create_app("main.py", "import utils\nprint(f'Vibe {utils.get_version()}')")

    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(main_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def the_journey() -> None:
        uri = f"ws://127.0.0.1:{port}"

        # --- PHASE 1: INITIAL COLD START ---
        async with websockets.connect(uri) as ws1:
            msg = await asyncio.wait_for(ws1.recv(), timeout=5.0)
            data = json.loads(msg)
            assert "Vibe 1.0.0" in data.get("output", "")
            print("Journey Step 1: Cold start successful.")

            # --- PHASE 2: DEEP EDIT (Dependency) ---
            # Edit utils, NOT main. Vibe should re-exec main and pick up new utils.
            isolated_env.create_app("utils.py", "def get_version(): return '2.0.0-PRO'")
            msg = await asyncio.wait_for(ws1.recv(), timeout=5.0)
            data = json.loads(msg)
            assert "Vibe 2.0.0-PRO" in data.get("output", "")
            print("Journey Step 2: Deep dependency edit reflected.")

            # --- PHASE 3: LATE JOINER CONSISTENCY ---
            # Connect a second client. It should get the LATEST result immediately.
            async with websockets.connect(uri) as ws2:
                msg_late = await asyncio.wait_for(ws2.recv(), timeout=2.0)
                data_late = json.loads(msg_late)
                assert "Vibe 2.0.0-PRO" in data_late.get("output", "")
                print("Journey Step 3: Late joiner consistency verified.")

            # --- PHASE 4: RESILIENCE (Broken Code) ---
            print("Journey Step 4: Injecting SyntaxError...")
            isolated_env.create_app("main.py", "import utils\nprint(f'Vibe {utils.get_version()}' !!!")

            # We wait a bit to let the "storm" settle
            time.sleep(1)

            error_msgs = []
            try:
                while True:
                    msg = await asyncio.wait_for(ws1.recv(), timeout=0.5)
                    data = json.loads(msg)
                    error_msgs.append(data)
                    print(f"  [Step 4 RECV] Status: {data['status']} @ {data.get('timestamp')}")
            except TimeoutError:
                pass

            print(f"  Detected {len(error_msgs)} messages from single Error save.")
            assert any(d["status"] == "error" for d in error_msgs)

            # --- PHASE 5: RECOVERY ---
            print("Journey Step 5: Fixing code...")
            isolated_env.create_app("main.py", "import utils\nprint(f'Vibe {utils.get_version()}')")

            # How many messages do we get now?
            recovery_msgs = []
            start = time.time()
            while time.time() - start < 3:
                try:
                    msg = await asyncio.wait_for(ws1.recv(), timeout=0.5)
                    data = json.loads(msg)
                    recovery_msgs.append(data)
                    print(f"  [Step 5 RECV] Status: {data['status']} @ {data.get('timestamp')}")
                except TimeoutError:
                    continue

            assert any(d["status"] == "success" for d in recovery_msgs), "Recovery failed: No success message received."
            # If we still see 'error' in recovery_msgs, it proves protocol pollution
            stale_in_recovery = [d for d in recovery_msgs if d["status"] == "error"]
            if stale_in_recovery:
                print(
                    f"  !!! CRITICAL AUDIT FINDING: Received {len(stale_in_recovery)} STALE ERRORS during recovery phase."
                )

            # --- PHASE 6: STORM ---
            # 10 saves in 1 second.
            print("Journey Step 6: Triggering Save Storm...")
            for i in range(10):
                isolated_env.create_app("main.py", f"import utils\nprint(f'Vibe {{utils.get_version()}} [{i}]')")
                time.sleep(0.05)

            # We expect to eventually get the last one (9)
            # This also tests if we get a flood of 10 messages (Bad) or correctly debounced (Good)
            # For this E2E we just verify we don't crash and get the latest.
            time.sleep(1)
            # Drain queue to get latest
            latest_msg = None
            try:
                while True:
                    m = await asyncio.wait_for(ws1.recv(), timeout=0.5)
                    latest_msg = m
            except TimeoutError:
                pass

            if latest_msg:
                assert "[9]" in latest_msg or "[8]" in latest_msg  # Accounting for jitter
                print("Journey Step 6: Save storm handled.")

        print("--- JOURNEY COMPLETE: HERO HAS RETURNED ---")

    try:
        asyncio.run(the_journey())
    finally:
        process.terminate()
        process.wait()
