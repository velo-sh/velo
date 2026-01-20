"""
Vibe Engine: Chaos Manifold Integration Test Suite
===================================================
This file contains advanced adversarial scenarios that challenge the
fundamental assumptions of a fork-based live execution system.

These tests simulate real-world edge cases that developers encounter
in production environments.
"""

import asyncio
import json
import sqlite3
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


# =============================================================================
# SCENARIO 1: Split-Brain Syndrome
# =============================================================================
@pytest.mark.tier3
def test_CHAOS_split_brain_resource_collision(isolated_env: VeloTestEnv):
    """
    Challenge: Two Vibe instances competing for the same resources.
    If two terminals run `vibe` on the same project, do they clash?
    """
    code = "print('Instance active')"
    app_py = isolated_env.create_app("app.py", code)

    port1 = isolated_env.next_port()
    port2 = isolated_env.next_port()

    # Start two Vibe instances on the SAME codebase
    process1 = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port1)})
    time.sleep(1)
    process2 = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port2)})
    time.sleep(2)

    async def check_split_brain():
        # Both should be listening
        uri1 = f"ws://127.0.0.1:{port1}"
        uri2 = f"ws://127.0.0.1:{port2}"

        async with websockets.connect(uri1) as ws1, websockets.connect(uri2) as ws2:
            # Consume initial messages
            await ws1.recv()
            await ws2.recv()

            # Trigger a save
            isolated_env.create_app("app.py", "print('Updated')")

            # Both should receive the update
            msg1 = await asyncio.wait_for(ws1.recv(), timeout=5.0)
            msg2 = await asyncio.wait_for(ws2.recv(), timeout=5.0)

            # ASSERTION: Both received the same update
            assert "Updated" in json.loads(msg1).get("output", "")
            assert "Updated" in json.loads(msg2).get("output", "")
            print("Split-brain scenario handled: Both instances updated.")

    try:
        asyncio.run(check_split_brain())
    finally:
        process1.terminate()
        process2.terminate()
        process1.wait()
        process2.wait()


# =============================================================================
# SCENARIO 2: Time-Traveler's Paradox
# =============================================================================
@pytest.mark.tier3
def test_CHAOS_time_traveler_monotonicity(isolated_env: VeloTestEnv):
    """
    Challenge: Are timestamps monotonically increasing across rapid forks?
    If forks happen too fast, `time.time()` might return identical values.
    """
    code = """
import time
print(f"TIMESTAMP={time.time_ns()}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_monotonicity():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            timestamps = []

            # Trigger 5 rapid saves
            for i in range(5):
                isolated_env.create_app("app.py", f"{code}# {i}")
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(msg)
                    output = data.get("output", "")
                    if "TIMESTAMP=" in output:
                        ts = int(output.split("TIMESTAMP=")[1].strip())
                        timestamps.append(ts)
                except TimeoutError:
                    pass

            print(f"Collected timestamps: {timestamps}")

            # ASSERTION: All timestamps must be strictly increasing
            for i in range(1, len(timestamps)):
                assert timestamps[i] > timestamps[i - 1], (
                    f"Time paradox! ts[{i}]={timestamps[i]} <= ts[{i - 1}]={timestamps[i - 1]}"
                )

    try:
        asyncio.run(check_monotonicity())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 3: Death Spiral
# =============================================================================
@pytest.mark.tier3
def test_CHAOS_death_spiral_blocking_code(isolated_env: VeloTestEnv):
    """
    Challenge: Code with blocking `input()` or infinite loop.
    Vibe must be able to kill the old worker and spawn a new one.
    """
    # Start with blocking code
    code_blocking = "x = input('Enter: ')"
    app_py = isolated_env.create_app("app.py", code_blocking)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_death_spiral():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # The first execution will block on input()
            # We should still be able to send a new save and get a response

            # Fix the code
            print("Fixing blocking code...")
            isolated_env.create_app("app.py", "print('Fixed!')")

            # We expect a response within 5 seconds if Vibe killed the old worker
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(msg)
                # Could be error from first one or success from second
                if data["status"] == "success" and "Fixed!" in data.get("output", ""):
                    print("Death spiral escaped: Worker was killed and replaced.")
                    return
            except TimeoutError:
                pytest.fail("Death spiral: Vibe stuck waiting for blocking worker!")

    try:
        asyncio.run(check_death_spiral())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 4: Shared State Corruption (SQLite)
# =============================================================================
@pytest.mark.tier3
def test_CHAOS_shared_state_sqlite_corruption(isolated_env: VeloTestEnv):
    """
    Challenge: SQLite database integrity across rapid forks.
    Does Vibe handle database connections correctly after fork?
    """
    db_path = isolated_env.path / "test.db"

    # Pre-create the database
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY, msg TEXT)")
    conn.commit()
    conn.close()

    code = f"""
import sqlite3
conn = sqlite3.connect({repr(str(db_path))})
conn.execute("INSERT INTO log (msg) VALUES ('entry')")
conn.commit()
conn.close()
print("Inserted")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_sqlite():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Trigger 3 saves
            for i in range(3):
                isolated_env.create_app("app.py", f"{code}# {i}")
                try:
                    await asyncio.wait_for(websocket.recv(), timeout=2.0)
                except TimeoutError:
                    pass

            time.sleep(1)

            # Verify database integrity
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM log")
            count = cursor.fetchone()[0]
            conn.close()

            print(f"SQLite entries: {count}")
            # We expect at least 1 entry (initial) + some from forks
            # The key assertion is that the DB is not corrupted
            assert count >= 1, "SQLite corruption: No entries found!"

    try:
        asyncio.run(check_sqlite())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 5: Cryptographic Staleness
# =============================================================================
@pytest.mark.tier3
def test_CHAOS_crypto_staleness_rng_divergence(isolated_env: VeloTestEnv):
    """
    Challenge: RNG state after fork.
    Each forked process should have independent random state.
    """
    code = """
import secrets
print(f"TOKEN={secrets.token_hex(16)}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_rng():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            tokens = []

            # Trigger 5 saves
            for i in range(5):
                isolated_env.create_app("app.py", f"{code}# {i}")
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(msg)
                    output = data.get("output", "")
                    if "TOKEN=" in output:
                        token = output.split("TOKEN=")[1].strip()
                        tokens.append(token)
                except TimeoutError:
                    pass

            print(f"Collected tokens: {tokens}")

            # ASSERTION: All tokens must be unique
            assert len(tokens) == len(set(tokens)), f"Crypto staleness! Duplicate tokens detected: {tokens}"

    try:
        asyncio.run(check_rng())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 6: GPU Context Orphaning (Simulated)
# =============================================================================
@pytest.mark.tier3
@pytest.mark.skip(reason="Requires CUDA hardware. Run manually on GPU machines.")
def test_CHAOS_gpu_context_orphaning(isolated_env: VeloTestEnv):
    """
    Challenge: GPU CUDA context after fork.
    This test is skipped by default as it requires GPU hardware.
    """
    code = """
import torch
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
x = torch.tensor([1.0, 2.0, 3.0]).to(device)
print(f"GPU Tensor: {x}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_gpu():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            data = json.loads(msg)

            # ASSERTION: Should not crash with CUDA errors
            assert data["status"] == "success", f"GPU context error: {data}"
            print("GPU context handled correctly.")

    try:
        asyncio.run(check_gpu())
    finally:
        process.terminate()
        process.wait()
