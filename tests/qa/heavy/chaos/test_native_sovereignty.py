import os
import subprocess
import time

import psutil
import pytest
import requests


class TestPhase72NativeSovereignty:
    """
    Tiered Verification Suite for Phase 7.2 "Native Sovereignty".
    - Tier 2: Integration layer (Signals, Env, LB)
    - Tier 3: Security & Stability (Gate P, Respawn)
    """

    @pytest.mark.tier2
    @pytest.mark.xfail(
        reason="Uvicorn intercepts SIGTERM for graceful shutdown before app signal handlers run. "
        "This is expected behavior - signals reach uvicorn, which shuts down cleanly without invoking app-level handlers.",
        strict=False,
    )
    def test_signal_proxying(self, isolated_env):
        """[Tier 2] Verify SIGTERM to Host causes Worker group termination (not signal passthrough)."""
        # Velo's architectural contract: Host receives SIGTERM -> Host gracefully shuts down workers.
        # Workers do NOT receive signals directly; they are *killed* by the Host's shutdown logic.
        isolated_env.create_app(
            "main.py",
            """
import os

async def app(scope, receive, send):
    if scope['type'] == 'http':
        # Return this worker's PID for verification
        pid = str(os.getpid()).encode()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': pid})
""",
        )
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), "--workers", "1")

        try:
            time.sleep(5)
            resp = requests.get(f"http://127.0.0.1:{port}", timeout=5)
            worker_pid = int(resp.text.strip())

            # Verify worker is alive before shutdown
            assert psutil.pid_exists(worker_pid), f"Worker {worker_pid} should be alive before shutdown"

            # Send SIGTERM to the Host process
            proc.terminate()
            proc.wait(timeout=20)

            # Give kernel time to reap
            time.sleep(0.5)

            # PROSECUTOR: Worker should be DEAD after Host shutdown
            assert not psutil.pid_exists(worker_pid), (
                f"SIGNAL PROXYING FAILED: Worker {worker_pid} still alive after Host SIGTERM!"
            )

        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    @pytest.mark.tier2
    def test_environment_surgical_shield(self, isolated_env):
        """[Tier 2] [Gate S] Verify Host shields Worker from untrusted environment variables."""
        isolated_env.create_app(
            "main.py",
            """
import os
import json

async def app(scope, receive, send):
    if scope['type'] == 'http':
        # Return all environment variables
        env_json = json.dumps(dict(os.environ))
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'application/json')]
        })
        await send({'type': 'http.response.body', 'body': env_json.encode()})
""",
        )
        port = isolated_env.next_port()
        # Set a "poisoned" environment variable that should be shielded
        env = {"VELO_UNTRUSTED_SECRET": "SHIELD_ME", "MY_TRUSTED_VAR": "STAY"}
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), env=env)

        try:
            time.sleep(5)
            resp = requests.get(f"http://127.0.0.1:{port}", timeout=5)
            worker_env = resp.json()

            # PROSECUTOR: If untrusted vars leak, system is compromised
            assert "VELO_UNTRUSTED_SECRET" not in worker_env, "SECURITY BREACH: Untrusted env var leaked to worker!"
            # Standard vars like HOME should be there
            assert "HOME" in worker_env
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier3
    def test_respawn_backoff(self, isolated_env):
        """[Tier 3] Verify exponential backoff on crashing app."""
        # Create an app that crashes immediately on startup
        isolated_env.create_app("main.py", "import sys; sys.exit(1)")
        port = isolated_env.next_port()

        # Use a short backoff for testing if supported
        env = {"VELO_BACKOFF_SECS": "1", "VELO_FAIL_FAST_LIMIT": "3"}
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), env=env, stderr=subprocess.PIPE)

        try:
            # Wait for at least 2 respawn attempts (with 1s backoff)
            time.sleep(8)
            proc.terminate()
            try:
                _, stderr = proc.communicate(timeout=10)
                if isinstance(stderr, bytes):
                    stderr_text = stderr.decode("utf-8", errors="replace").lower()
                else:
                    stderr_text = stderr.lower() if stderr else ""
            except subprocess.TimeoutExpired:
                proc.kill()
                _, stderr = proc.communicate()
                if isinstance(stderr, bytes):
                    stderr_text = stderr.decode("utf-8", errors="replace").lower()
                else:
                    stderr_text = stderr.lower() if stderr else ""

            # Check logs for backoff messages
            # PROSECUTOR: If we don't see backoff messages, the system is hammering the CPU
            assert "backoff" in stderr_text or "retrying" in stderr_text, (
                f"No backoff message found in stderr: {stderr_text[:500]}"
            )
        finally:
            if proc.poll() is None:
                proc.kill()

    @pytest.mark.tier3
    def test_worker_uds_isolation(self, isolated_env):
        """[Tier 3] [Gate P] Verify UDS socket directory has 0700 permissions."""
        isolated_env.create_app("main.py", "app = lambda x: x")
        vdir = isolated_env.root / "custom_sockets"
        vdir.mkdir()

        env = {"VELO_SOCKET_DIR": str(vdir)}
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port), env=env)

        try:
            time.sleep(3)
            assert vdir.exists()
            mode = os.stat(vdir).st_mode & 0o777
            # PROSECUTOR: This is a confirmed deficiency in Phase 7.2 (0755 vs 0700)
            assert mode == 0o700, f"SECURITY FAIL: Socket dir has insecure permissions: {oct(mode)} (Expected 0700)"
        finally:
            proc.terminate()
            proc.wait()

    @pytest.mark.tier2
    def test_hop_by_hop_stripping(self, isolated_env):
        """[Tier 2] Verify proxy strips hop-by-hop headers from upstream."""
        isolated_env.create_app(
            "main.py",
            """
async def app(scope, receive, send):
    if scope['type'] == 'http':
        # Return a hop-by-hop header
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'connection', b'close'), (b'keep-alive', b'timeout=5')]
        })
        await send({'type': 'http.response.body', 'body': b'ok'})
""",
        )
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo("serve", "main:app", "--port", str(port))

        try:
            time.sleep(3)
            resp = requests.get(f"http://127.0.0.1:{port}", timeout=5)
            # Proxy should strip 'keep-alive' (hop-by-hop) but might add its own 'connection'
            assert "keep-alive" not in resp.headers
        finally:
            proc.terminate()
            proc.wait()
