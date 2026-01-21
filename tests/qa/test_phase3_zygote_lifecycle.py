from __future__ import annotations

"""
Velo QA: Phase 3 Zygote Lifecycle Chaos Tests (ZYG-CHAOS-xxx)
==============================================================
Adversarial tests targeting Zygote daemon lifecycle.

Goal: Break the Zygote daemon through unexpected lifecycle events!
"""

import os
import signal
import time

from test_harness import assert_no_crash, run_velo
from test_phase3_harness import (
    ZygoteTestEnv,
    count_zombie_processes,
)


class TestZygoteLifecycleCHAOS:
    """ZYG-CHAOS-xxx: Zygote daemon lifecycle chaos tests."""

    def test_zyg_chaos_001_kill_during_startup(self):
        """
        ZYG-CHAOS-001: Kill Zygote during startup.

        Attack: SIGKILL during initialization.
        Expected: No orphan processes, no corrupted state.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            initial_zombies = count_zombie_processes()

            # Start Zygote in background
            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            # If it started, kill it immediately
            if env.zygote_pid:
                os.kill(env.zygote_pid, signal.SIGKILL)
                time.sleep(0.5)

            # Check no zombie processes created
            final_zombies = count_zombie_processes()
            assert final_zombies <= initial_zombies, f"Zombie processes created: {final_zombies - initial_zombies}"

            # Socket should not exist or should be cleaned
            # (depending on implementation)
        finally:
            env.cleanup()

    def test_zyg_chaos_003_double_start(self):
        """
        ZYG-CHAOS-003: Attempt to start Zygote twice.

        Attack: Start Zygote when already running.
        Expected: Second start fails gracefully with clear message.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # First start
            result1 = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            if result1.success:
                # Try second start
                result2 = run_velo(["zygote", "start"], cwd=env.path, timeout=5)

                assert_no_crash(result2)
                # Should fail gracefully
                assert (
                    not result2.success or "already" in result2.stdout.lower() or "running" in result2.stdout.lower()
                ), "Second start should fail or indicate already running"
        finally:
            env.cleanup()

    def test_zyg_chaos_004_stop_non_running(self):
        """
        ZYG-CHAOS-004: Stop Zygote when not running.

        Attack: Stop command with no daemon.
        Expected: Clear error message, no crash.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Don't start, just stop
            result = run_velo(["zygote", "stop"], cwd=env.path, timeout=5)

            assert_no_crash(result)
            # Should give clear message (not crash)
        finally:
            env.cleanup()

    def test_zyg_chaos_005_stale_socket_file(self):
        """
        ZYG-CHAOS-005: Stale socket file exists but no process.

        Attack: Create socket file without daemon.
        Expected: Auto-cleanup and start, or clear error.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create cache dir and fake socket
            env.socket_path.parent.mkdir(parents=True, exist_ok=True)
            env.socket_path.touch()  # Create regular file as "stale socket"

            # Try to start
            result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            assert_no_crash(result)
            # Should either clean up and start, or give clear error
        finally:
            env.cleanup()

    def test_zyg_chaos_007_rapid_start_stop_cycle(self):
        """
        ZYG-CHAOS-007: Rapid start/stop cycles.

        Attack: 5x start/stop in quick succession.
        Expected: No resource leak, no crashes.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            initial_zombies = count_zombie_processes()

            for i in range(5):
                run_velo(["zygote", "start"], cwd=env.path, timeout=5)
                run_velo(["zygote", "stop"], cwd=env.path, timeout=5)

            # Final cleanup
            time.sleep(0.5)
            final_zombies = count_zombie_processes()

            # No zombie accumulation
            assert final_zombies <= initial_zombies + 1, (
                f"Zombie leak after rapid cycles: {final_zombies - initial_zombies}"
            )
        finally:
            env.cleanup()


class TestZygoteStatus:
    """Tests for velo zygote status command."""

    def test_status_when_running(self):
        """Status should show running Zygote info."""
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Start Zygote
            start_result = run_velo(["zygote", "start"], cwd=env.path, timeout=10)

            if start_result.success:
                # Check status
                status_result = run_velo(["zygote", "status"], cwd=env.path, timeout=5)
                assert_no_crash(status_result)

                if status_result.success:
                    # Should contain some status info
                    output = status_result.stdout.lower()
                    assert any(word in output for word in ["running", "pid", "uptime"]), (
                        "Status should show running state"
                    )
        finally:
            env.cleanup()

    def test_status_when_not_running(self):
        """Status should indicate not running."""
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Don't start, check status
            result = run_velo(["zygote", "status"], cwd=env.path, timeout=5)
            assert_no_crash(result)
            # Should indicate not running (not crash)
        finally:
            env.cleanup()
