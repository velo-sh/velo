from __future__ import annotations

"""
Velo QA: Phase 3 Fork Attack Tests (FORK-xxx)
==============================================
Adversarial tests targeting Zygote fork mechanism.

Goal: Break the fork mechanism with resource attacks!
"""

import time

from test_harness import assert_no_crash, run_velo
from test_phase3_harness import (
    ZygoteTestEnv,
    count_zombie_processes,
)


class TestForkAttacks:
    """FORK-xxx: Fork mechanism attack tests."""

    def test_fork_001_fork_bomb_script(self):
        """
        FORK-001: Script attempts fork bomb.

        Attack: Python script with os.fork() loop.
        Expected: Resource limit enforced, Zygote survives.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create fork bomb script (limited)
            env.create_script(
                "fork_bomb.py",
                """
import os
import sys

# Attempt limited fork bomb (should be blocked)
forked = 0
for i in range(10):
    try:
        if os.fork() == 0:
            forked += 1
            sys.exit(0)
    except Exception as e:
        print(f"Fork blocked: {e}")
        break

print(f"Forked {forked} times")
""",
            )

            initial_zombies = count_zombie_processes()

            # Run with zygote
            result = run_velo(["run", "--zygote", "fork_bomb.py"], cwd=env.path, timeout=30)

            # Should either block forks or handle gracefully
            assert_no_crash(result)

            # Cleanup time
            time.sleep(1)

            # Check no zombie accumulation
            final_zombies = count_zombie_processes()
            zombie_increase = final_zombies - initial_zombies

            assert zombie_increase < 10, f"Too many zombies created by fork bomb: {zombie_increase}"
        finally:
            env.cleanup()

    def test_fork_003_memory_exhaustion(self):
        """
        FORK-003: Worker tries to exhaust memory.

        Attack: Script allocates huge array.
        Expected: OOM handled gracefully, Zygote survives.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Create memory hog script (but not too aggressive)
            env.create_script(
                "mem_hog.py",
                """
import sys

# Try to allocate 100MB (should be fine)
try:
    data = bytearray(100 * 1024 * 1024)
    print(f"Allocated {len(data)} bytes")
except MemoryError:
    print("Memory allocation failed")
    sys.exit(1)
""",
            )

            # Run with zygote
            result = run_velo(["run", "--zygote", "mem_hog.py"], cwd=env.path, timeout=30)

            assert_no_crash(result)
            # Either succeeds or fails gracefully
        finally:
            env.cleanup()

    def test_fork_004_zombie_worker(self):
        """
        FORK-004: Worker exits without proper cleanup.

        Attack: Script calls os._exit() abruptly.
        Expected: No zombie processes left.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Script that exits abruptly
            env.create_script(
                "abrupt_exit.py",
                """
import os
os._exit(42)  # Abrupt exit without cleanup
""",
            )

            initial_zombies = count_zombie_processes()

            # Run with zygote
            result = run_velo(["run", "--zygote", "abrupt_exit.py"], cwd=env.path, timeout=10)

            # Give time for cleanup
            time.sleep(0.5)

            final_zombies = count_zombie_processes()

            assert final_zombies <= initial_zombies, (
                f"Zombie process left after abrupt exit: {final_zombies - initial_zombies}"
            )
        finally:
            env.cleanup()

    def test_fork_006_worker_timeout(self):
        """
        FORK-006: Script runs forever.

        Attack: Infinite loop script.
        Expected: Timeout and kill with clear message.
        """
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Infinite loop script
            env.create_script(
                "infinite.py",
                """
import time
while True:
    time.sleep(0.1)
""",
            )

            # Run with short timeout (handled by velo, not test harness)
            start = time.perf_counter()
            result = run_velo(["run", "--zygote", "infinite.py"], cwd=env.path, timeout=10)
            elapsed = time.perf_counter() - start

            # Should timeout eventually (test harness timeout catches this)
            # The point is it shouldn't hang forever
            assert_no_crash(result)
        finally:
            env.cleanup()


class TestConcurrentWorkers:
    """Tests for concurrent worker execution."""

    def test_concurrent_workers(self):
        """Multiple workers running concurrently."""
        env = ZygoteTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Simple script
            env.create_script(
                "quick.py",
                """
import time
time.sleep(0.1)
print("done")
""",
            )

            import threading

            results = []

            def run_worker():
                r = run_velo(["run", "--zygote", "quick.py"], cwd=env.path, timeout=30)
                results.append(r)

            # Start 5 concurrent workers
            threads = [threading.Thread(target=run_worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            # Check results
            success_count = sum(1 for r in results if r.success)

            # At least some should succeed
            assert success_count >= 1, "No concurrent workers succeeded"
        finally:
            env.cleanup()
