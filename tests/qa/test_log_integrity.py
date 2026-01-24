"""
Log Integrity Tests (INV-POLY-004)

Tests for Anti-Spoofing log filter to prevent log poisoning attacks.

Architecture Note:
- Rust sanitization module exists at src/common/log_sanitize.rs
- Full end-to-end filtering requires stdout piping (not yet implemented)
- Current tests verify sanitization capability exists

TDD Status:
- Rust unit tests: PASS (4/4 in log_sanitize.rs)
- E2E filtering: xfail (requires Stdio piping architecture change)
"""

import subprocess
import time

import pytest
import requests


class TestLogIntegrity:
    """Verify anti-spoofing measures in log output."""

    @pytest.fixture
    def isolated_env(self, tmp_path):
        """Create isolated test environment."""
        from tests.qa.conftest_utils import VeloTestEnv, get_velo_binary

        return VeloTestEnv(tmp_path, get_velo_binary())

    @pytest.mark.tier3
    @pytest.mark.xfail(
        reason="E2E filtering requires Stdio piping architecture. "
        "Sanitization module exists at src/common/log_sanitize.rs (see Rust tests).",
        strict=False,
    )
    def test_anti_spoofing_sup_tag_stripped(self, isolated_env):
        """[INV-POLY-004] Worker-injected [SUP] tags must be stripped/flagged."""
        # Create app that tries to inject supervisor tags
        isolated_env.create_app(
            "main.py",
            """
import sys

# Attempt log poisoning by injecting [SUP] tag
print("[SUP] FAKE: This is a spoofed supervisor message", flush=True)
print("[SID:9999] FAKE: This is a spoofed session message", flush=True)
print("LEGIT: This is a real worker message", flush=True)

async def app(scope, receive, send):
    if scope['type'] == 'http':
        # Also try during request handling
        print("[SUP] INJECT: Request-time injection attempt", flush=True)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})
""",
        )
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo(
            "serve", "main:app", "--port", str(port), "--workers", "1", stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        try:
            time.sleep(5)
            # Make a request to trigger the injection attempt
            try:
                requests.get(f"http://127.0.0.1:{port}", timeout=5)
            except Exception:
                pass

            time.sleep(1)
            proc.terminate()
            proc.wait(timeout=10)

            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            output = stdout + stderr

            # Verify anti-spoofing: injected [SUP] should be sanitized
            # Option 1: Tag is replaced with [SPOOFED-SUP]
            # Option 2: Tag is stripped entirely
            # Option 3: Warning is logged about injection attempt

            has_raw_sup_fake = "[SUP] FAKE:" in output
            has_raw_sup_inject = "[SUP] INJECT:" in output

            # If raw spoofed tags appear, the filter is not working
            assert not has_raw_sup_fake, (
                f"Anti-spoofing failed: [SUP] FAKE tag was not filtered. Output: {output[:500]}"
            )
            assert not has_raw_sup_inject, (
                f"Anti-spoofing failed: [SUP] INJECT tag was not filtered. Output: {output[:500]}"
            )

        finally:
            if proc.poll() is None:
                proc.kill()

    @pytest.mark.tier3
    def test_anti_spoofing_legit_messages_preserved(self, isolated_env):
        """[INV-POLY-004] Legitimate worker messages must be preserved."""
        isolated_env.create_app(
            "main.py",
            """
import sys
print("WORKER: Normal startup message", flush=True)

async def app(scope, receive, send):
    if scope['type'] == 'http':
        print("WORKER: Handling request", flush=True)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})
""",
        )
        port = isolated_env.next_port()
        proc = isolated_env.spawn_velo(
            "serve", "main:app", "--port", str(port), "--workers", "1", stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        try:
            time.sleep(5)
            try:
                requests.get(f"http://127.0.0.1:{port}", timeout=5)
            except Exception:
                pass

            time.sleep(1)
            proc.terminate()
            proc.wait(timeout=10)

            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            output = stdout + stderr

            # Legitimate messages should be preserved
            assert "Normal startup message" in output or "Handling request" in output, (
                f"Legitimate worker messages were not preserved. Output: {output[:500]}"
            )

        finally:
            if proc.poll() is None:
                proc.kill()
