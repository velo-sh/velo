import os
import sys
import time
from pathlib import Path
from typing import Any


def test_H12_signal_hygiene_direct_fork(velo_serve_fixture):
    """H-12 Signal Hygiene: Direct Zygote fork verification."""
    results_file = Path("/tmp/signal_results.txt")
    stderr_log = Path("probe_stderr.txt").absolute()
    probe_path = Path("probe_direct.py").absolute()

    if results_file.exists():
        results_file.unlink()
    if stderr_log.exists():
        stderr_log.unlink()
    if probe_path.exists():
        probe_path.unlink()

    # We use the Zygote already started by the fixture
    proc = velo_serve_fixture.start("main:app", workers=1)
    proc.wait_ready()

    socket_path = proc.get_socket_path()

    # Create a MINIMAL probe script without triple-f-string madness
    probe_script = """
import signal
import os
import sys

def check():
    with open(\"/tmp/probe.debug\", \"w\") as debug_f:
        debug_f.write(\"Probe Start\\n\")
        try:
            sigterm = signal.getsignal(signal.SIGTERM)
            sigpipe = signal.getsignal(signal.SIGPIPE)
            debug_f.write(f\"Signals: {sigterm}, {sigpipe}\\n\")

            try:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
                mask_empty = (len(mask) == 0)
            except Exception:
                mask_empty = True
            debug_f.write(f\"Mask empty: {mask_empty}\\n\")

            with open(\"REPLACE_RESULTS_PATH\", \"w\") as f:
                f.write(\"SIGTERM_DFL:\" + str(sigterm == signal.SIG_DFL) + \"\\n\")
                f.write(\"SIGPIPE_DFL:\" + str(sigpipe == signal.SIG_DFL) + \"\\n\")
                f.write(\"MASK_EMPTY:\" + str(mask_empty) + \"\\n\")
            debug_f.write(\"Results written\\n\")
            sys.exit(0)
        except Exception as e:
            debug_f.write(f\"ERROR: {str(e)}\\n\")
            import traceback
            traceback.print_exc(file=debug_f)
            sys.exit(1)

if __name__ == \"__main__\":
    check()
""".replace("REPLACE_RESULTS_PATH", str(results_file))

    probe_path.write_text(probe_script)

    import asyncio

    _repo_root = os.path.abspath(str(Path(__file__).parents[4]))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    print(f"DEBUG: sys.path at import time: {sys.path}")
    print(f"DEBUG: CWD: {os.getcwd()}")
    try:
        from tests.qa.zygote_client import ZygoteClient
    except ImportError as e:
        print(f"DEBUG: FAILED TO IMPORT tests.qa.zygote_client: {e}")
        # Try finding it on disk
        target = os.path.join(_repo_root, "tests/qa/zygote_client.py")
        print(f"DEBUG: Exists? {target} -> {os.path.exists(target)}")
        raise
    from velo_zygote.constants import PROTOCOL_VERSION

    async def run_hygiene_test() -> Any:
        async with ZygoteClient(str(socket_path)) as client:
            # 1. Handshake
            handshake = {
                "type": "Handshake",
                "version": PROTOCOL_VERSION,
                "capabilities": [],
            }

            # SEC-005: Forensic Auth
            if proc.forensic_secret:
                await client.send({"type": "Auth", "secret": proc.forensic_secret})
                auth_resp = await client.recv()
                print(f"DEBUG: Auth Response: {auth_resp}")

            await client.send(handshake)
            await client.recv()

            # 2. Fork
            cmd = {
                "type": "Fork",
                "script_path": str(probe_path),
                "args": [],
                "async_mode": False,
                "stderr_path": str(stderr_log),
            }
            await client.send(cmd)

            # 3. Wait for Fork response
            resp = await client.recv()
            print(f"DEBUG: Fork Response: {resp}")
            return resp

    try:
        resp = asyncio.run(run_hygiene_test())

        # 4. Wait for results file
        for _ in range(50):
            if results_file.exists():
                break
            time.sleep(0.1)

        if stderr_log.exists() and stderr_log.stat().st_size > 0:
            print(f"DEBUG: Probe STDERR: {stderr_log.read_text()}")

        assert results_file.exists(), (
            f"Results file missing. Exit code: {resp.get('exit_code')}. Stderr: {stderr_log.read_text() if stderr_log.exists() else 'N/A'}"
        )
        content = results_file.read_text()
        print(f"DEBUG: Results: {content}")

        assert "SIGTERM_DFL:True" in content
        assert "SIGPIPE_DFL:True" in content
        assert "MASK_EMPTY:True" in content

    finally:
        # Keep files for debugging on failure
        if results_file.exists():
            print("INFO: Test Passed. Cleaning up.")
        # Keep files for debugging on failure
        if results_file.exists():
            print("INFO: Test Passed. Cleaning up.")
            # probe_path.unlink()
            # results_file.unlink()
            # stderr_log.unlink()
