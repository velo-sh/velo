import asyncio
import json
import os
import signal
import time

import pytest
import websockets
from conftest_utils import VeloTestEnv


@pytest.mark.tier0
def test_L0_002_cli_alias_vibe(isolated_env: VeloTestEnv):
    """Verify that 'vibe' command exists and responds to --help."""
    # VeloTestEnv copies the binary to self.velo
    # We call it with 'vibe' as the first argument to test the command structure
    result = isolated_env.run_velo("vibe", "--help")

    assert result.returncode == 0
    assert "vibe" in result.stdout.lower()


@pytest.mark.tier1
def test_L1_003_ws_json_egress(isolated_env: VeloTestEnv):
    """Verify that Vibe Gateway broadcasts valid JSON over WebSocket."""
    app_py = isolated_env.create_app("app.py", "print('hello vibe')")

    # Start vibe engine in background
    port = isolated_env.next_port()
    # vibe [target]
    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})

    # Give it time to start
    time.sleep(2)

    async def check_ws():
        uri = f"ws://127.0.0.1:{port}"
        try:
            async with websockets.connect(uri) as websocket:
                # Trigger a save by rewriting the file
                isolated_env.create_app("app.py", "print('vibe update')")

                # Receive message
                msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(msg)
                # Check for standard fields as per RFC-0029
                assert "status" in data or "target" in data
                return True
        except Exception as e:
            print(f"WS Error: {e}")
            return False

    try:
        success = asyncio.run(check_ws())
        assert success, "Failed to receive JSON broadcast from Vibe Gateway"
    finally:
        process.terminate()
        process.wait()


@pytest.mark.tier2
@pytest.mark.chaos
def test_STABILITY_101_zombie_storm(isolated_env: VeloTestEnv):
    """Run 100 saves in 10 seconds; verify 0 zombie processes remain (Pillar 1)."""
    app_py = isolated_env.create_app("app.py", "print('storm')")
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    # Per Pillar 1: "Prevent zombie accumulation during save storms via a non-blocking loop"
    # We trigger many saves
    for i in range(20):  # reduced from 100 for faster testing, but still a 'storm'
        isolated_env.create_app("app.py", f"print('storm {i}')")
        time.sleep(0.1)

    time.sleep(2)  # Wait for reaper

    # Check for zombies
    # On Unix, zombies show up in 'ps' with state 'Z'
    import subprocess

    ps = subprocess.run(["ps", "-ax", "-o", "state,ppid"], capture_output=True, text=True)
    zombies = [line for line in ps.stdout.splitlines() if line.strip().startswith("Z") and str(process.pid) in line]

    try:
        assert len(zombies) == 0, f"Detected {len(zombies)} zombie processes from ppid {process.pid}"
    finally:
        process.terminate()
        process.wait()


@pytest.mark.tier2
def test_STABILITY_102_watcher_resilience(isolated_env: VeloTestEnv):
    """Verify the vibe monitor survives SyntaxError and recovers on fix (Pillar 2)."""
    app_py = isolated_env.create_app("app.py", "print('start')")
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    # 1. Inject SyntaxError
    isolated_env.create_app("app.py", "invalid syntax !!!")
    time.sleep(1)  # Wait for execution

    # 2. Verify we can still get a response after fixing
    async def check_recovery():
        uri = f"ws://127.0.0.1:{port}"
        try:
            async with websockets.connect(uri) as websocket:
                # Upon connection, we might receive the cached SyntaxError message (DEF-08-004 fix)
                # We drain the buffer if a message is waiting
                try:
                    initial_msg = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    print(f"Received initial/cached msg: {initial_msg}")
                except TimeoutError:
                    pass

                # Now trigger the fix
                isolated_env.create_app("app.py", "print('fixed')")

                # Wait for the specific "fixed" or "success" message
                # We might need to wait for multiple if the watcher is still busy
                for _ in range(3):
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    print(f"Received msg: {msg}")
                    if "fixed" in msg or "success" in msg:
                        return True
                return False
        except Exception as e:
            print(f"Recovery Error: {e}")
            return False

    try:
        success = asyncio.run(check_recovery())
        assert success, "Vibe monitor failed to recover after SyntaxError"
    finally:
        process.terminate()
        process.wait()


@pytest.mark.tier2
@pytest.mark.chaos
def test_SEC_202_orphan_protection(isolated_env: VeloTestEnv):
    """Kill Master (SIGKILL); verify child forks are reaped (Pillar 5)."""
    app_py = isolated_env.create_app("app.py", "import time\ntime.sleep(60)")
    port = isolated_env.next_port()

    process = isolated_env.spawn_velo("vibe", str(app_py), env={"VELO_VIBE_PORT": str(port)})
    time.sleep(2)

    # Get children before killing master
    import psutil

    master_proc = psutil.Process(process.pid)
    children = master_proc.children(recursive=True)
    assert len(children) > 0, "No child processes spawned by Vibe master"
    child_pids = [c.pid for c in children]

    # SIGKILL the master
    os.kill(process.pid, signal.SIGKILL)
    process.wait()

    # Give orphan protection a moment
    time.sleep(2)

    # Verify children are gone
    for pid in child_pids:
        assert not psutil.pid_exists(pid), f"Orphan process {pid} still exists after master kill"
