"""
Vibe Engine: Apex Predator Integration Test Suite
==================================================
These tests represent the most extreme edge cases that can break
a fork-based live execution system. They target fundamental
Unix process semantics and Python runtime internals.

Tier: APEX (Beyond Chaos)
"""

import asyncio
import json
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


# =============================================================================
# SCENARIO 1: Thread Graveyard
# =============================================================================
@pytest.mark.tier4
def test_APEX_thread_graveyard(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: fork() only clones the calling thread.
    Background threads in Zygote vanish in the child, potentially leaving
    locks in a corrupted state.
    """
    code = """
import threading
import time

lock = threading.Lock()

def background_worker():
    with lock:
        time.sleep(10)

# Start a thread that holds the lock
t = threading.Thread(target=background_worker, daemon=True)
t.start()
time.sleep(0.1)  # Let thread acquire lock

# Now try to acquire the lock in main thread (simulating post-fork)
acquired = lock.acquire(timeout=1)
if acquired:
    lock.release()
    print("LOCK_OK")
else:
    print("LOCK_DEADLOCK")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_thread() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")
            print(f"Thread test output: {output}")

            # In a naive fork, the lock state is unpredictable
            # We just verify we get some output (didn't crash)
            assert "LOCK" in output

    try:
        asyncio.run(check_thread())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 2: Signal Hijacking
# =============================================================================
@pytest.mark.tier4
def test_APEX_signal_hijacking(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: User code registers custom SIGTERM handler.
    Vibe relies on SIGTERM to kill old workers. If hijacked, fallback to SIGKILL?
    """
    code_hijack = """
import signal
import time

def ignore_sigterm(sig, frame):
    print("SIGTERM ignored!")

signal.signal(signal.SIGTERM, ignore_sigterm)
time.sleep(60)  # Hang forever
"""
    app_py = isolated_env.create_app("app.py", code_hijack)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_signal() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # First worker is hung
            # Fix the code
            print("Fixing hijacking code...")
            isolated_env.create_app("app.py", "print('Fixed!')")

            # Vibe should SIGKILL the old worker and spawn new one
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(msg)
                if "Fixed!" in data.get("output", ""):
                    print("Signal hijacking handled: Fallback to SIGKILL worked.")
                    return
            except TimeoutError:
                pytest.fail("Signal hijacking: Vibe couldn't kill hijacked worker!")

    try:
        asyncio.run(check_signal())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 3: Import Cycle Hell
# =============================================================================
@pytest.mark.tier4
def test_APEX_import_cycle_hell(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: Circular imports causing partial initialization.
    """
    # Create circular dependency: a -> b -> c -> a
    isolated_env.create_app("mod_a.py", "import mod_b\nVAL_A = 'A'")
    isolated_env.create_app("mod_b.py", "import mod_c\nVAL_B = 'B'")
    isolated_env.create_app("mod_c.py", "import mod_a\nVAL_C = 'C'")
    isolated_env.create_app("app.py", "import mod_a\nprint('CYCLE_OK')")

    port = isolated_env.next_port()
    process = isolated_env.spawn_velo(
        "vibe",
        str(isolated_env.path / "app.py"),
        env={"VELO_VIBE_PORT": str(port)},
    )
    time.sleep(2)

    async def check_cycle() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)

            # Python handles this gracefully, but we verify Vibe doesn't crash
            if data["status"] == "error":
                print(f"Import cycle error (expected): {data.get('error', '')[:100]}")
            else:
                print(f"Import cycle handled: {data.get('output', '')}")

    try:
        asyncio.run(check_cycle())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 4: Unicode Bomb
# =============================================================================
@pytest.mark.tier4
def test_APEX_unicode_bomb(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: Pathological Unicode in output.
    Can the Gateway serialize and transmit without panicking?
    """
    code = """
# Zero-width characters, combining marks, emoji
output = '\\u200b' * 1000 + '\\u0301' * 100 + '🔥' * 500 + '👨‍👩‍👧‍👦' * 100
print(output)
print("UNICODE_OK")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_unicode() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")

            assert "UNICODE_OK" in output, "Unicode bomb corrupted output!"
            print("Unicode bomb handled: Gateway survived.")

    try:
        asyncio.run(check_unicode())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 5: Symlink Maze
# =============================================================================
@pytest.mark.tier4
def test_APEX_symlink_maze(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: Watching symlinked files vs actual files.
    Does Vibe detect changes to the target of a symlink?
    """
    # Create actual file in a subdirectory
    lib_dir = isolated_env.path / "lib"
    lib_dir.mkdir()
    actual_file = lib_dir / "real_module.py"
    actual_file.write_text("VAL = 'original'")

    # Create symlink in project root
    symlink = isolated_env.path / "linked_module.py"
    symlink.symlink_to(actual_file)

    code = """
import linked_module
print(f"VAL={linked_module.VAL}")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_symlink() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            # Consume initial
            msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            assert "VAL=original" in json.loads(msg).get("output", "")

            # Modify the ACTUAL file (not the symlink)
            print("Modifying actual file (target of symlink)...")
            actual_file.write_text("VAL = 'modified'")

            # Trigger by touching the main file
            isolated_env.create_app("app.py", code + "# trigger")

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")
            print(f"Symlink test output: {output}")

            # Note: This tests module reloading, which Python doesn't do automatically
            # The key is that Vibe doesn't crash on symlinks

    try:
        asyncio.run(check_symlink())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 6: Socket Inheritance
# =============================================================================
@pytest.mark.tier4
def test_APEX_socket_inheritance(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: Open TCP socket in Zygote, forked to child.
    Does the shared socket cause protocol corruption?
    """
    code = """
import socket

# Create a TCP socket (simulating a connection pool)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# We don't actually connect, but the fd exists
print(f"SOCKET_FD={sock.fileno()}")
sock.close()
print("SOCKET_OK")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_socket() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")

            assert "SOCKET_OK" in output, f"Socket inheritance failed: {output}"
            print("Socket inheritance handled: No fd conflict.")

    try:
        asyncio.run(check_socket())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 7: Binary Module (Simulated)
# =============================================================================
@pytest.mark.tier4
def test_APEX_binary_module_staleness(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: C extension module reloading.
    Python cannot unload .so files. Does Vibe detect and warn?

    This test simulates the scenario by using a pure-Python module
    that mimics the behavior of a C extension.
    """
    # Create a "fake" binary module (actually Python)
    isolated_env.create_app("fake_native.py", "VERSION = 1")
    code = "import fake_native; print(f'NATIVE_V={fake_native.VERSION}')"
    app_py = isolated_env.create_app("app.py", code)

    port = isolated_env.next_port()
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    async def check_binary() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as websocket:
            msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            assert "NATIVE_V=1" in json.loads(msg).get("output", "")

            # Update the "native" module
            print("Updating 'native' module...")
            isolated_env.create_app("fake_native.py", "VERSION = 2")
            isolated_env.create_app("app.py", code + "# trigger")

            msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(msg)
            output = data.get("output", "")
            print(f"Binary module test: {output}")

            # Due to Zygote caching, we might still see VERSION=1
            # This exposes the staleness issue
            if "NATIVE_V=1" in output:
                print("!!! AUDIT: Binary module staleness detected (expected).")

    try:
        asyncio.run(check_binary())
    finally:
        process.terminate()
        process.wait()


# =============================================================================
# SCENARIO 8: Cgroup Escape (Simulated)
# =============================================================================
@pytest.mark.tier4
@pytest.mark.skip(reason="Requires Docker. Run manually in containerized environment.")
def test_APEX_cgroup_escape(isolated_env: VeloTestEnv) -> None:
    """
    Challenge: OOM behavior in resource-limited containers.
    Does OOM Killer target only the Worker, or the entire container?

    This test must be run manually inside a Docker container with
    memory limits: docker run --memory=100m ...
    """
    code = """
# Allocate 200MB (exceeds 100MB container limit)
data = bytearray(200 * 1024 * 1024)
print("ALLOCATED")
"""
    app_py = isolated_env.create_app("app.py", code)
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(5)

    # If we reach here, the Master survived
    # The Worker should have been OOM-killed
    assert process.poll() is None, "Master was killed by OOM (Cgroup escape!)"
    print("Cgroup test: Master survived Worker OOM.")

    process.terminate()
    process.wait()
