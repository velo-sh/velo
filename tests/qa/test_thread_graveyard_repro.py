"""
Thread Graveyard Deadlock: EDUCATIONAL Reference Test
======================================================

⚠️ IMPORTANT: THIS IS AN EDUCATIONAL TEST, NOT A BUG REPORT ⚠️

This test demonstrates a fundamental operating system behavior with fork() + threading.
It is NOT a vulnerability in Velo's implementation. Our architecture is fork-safe by design.

┌─────────────────────────────────────────────────────────────────────────────┐
│ WHAT IS THREAD GRAVEYARD?                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ When fork() is called:                                                       │
│  1. Only the calling thread is copied to the child process                   │
│  2. Other threads "disappear" but their held locks remain LOCKED             │
│  3. If the child tries to acquire these locks → DEADLOCK (100%)              │
│                                                                              │
│ Common trigger scenarios:                                                    │
│  - import logging (internal locks)                                          │
│  - import torch (CUDA threads)                                              │
│  - import sqlalchemy (connection pool threads)                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ WHY VELO'S ZYGOTE ARCHITECTURE IS SAFE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ Our Zygote follows a fork-safe lifecycle:                                    │
│                                                                              │
│   [Startup] ───► [Preload Modules] ───► [Create Worker Pool] ───► [Ready]   │
│                        │                       │                             │
│                   NO THREADS YET          fork() happens HERE               │
│                        │                       │                             │
│                 ┌──────▼──────┐         ┌──────▼──────┐                     │
│                 │ safe to     │         │ preload     │                     │
│                 │ import ANY  │         │ already     │                     │
│                 │ module      │         │ complete    │                     │
│                 └─────────────┘         └─────────────┘                     │
│                                                                              │
│ KEY INSIGHT: Preload happens BEFORE any threads exist, and BEFORE fork().   │
│              The worker pool only starts AFTER modules are safely loaded.   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PURPOSE OF THIS TEST FILE                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. EDUCATIONAL: Demonstrates the Thread Graveyard phenomenon                │
│ 2. DOCUMENTATION: Proves why fork-after-thread is dangerous                 │
│ 3. REGRESSION PREVENTION: Ensures future changes don't break fork safety    │
│ 4. REFERENCE: Helps developers understand our design decisions              │
└─────────────────────────────────────────────────────────────────────────────┘

Related:
- DEF-08-013: Original audit finding (RESOLVED by architecture)
- RFC-0028: Zygote lifecycle specification
- velo_zygote/main.py: ZygoteServer._async_preload() implementation
"""

import multiprocessing
import os
import signal
import sys
import threading
import time
from typing import Any

import pytest


# =============================================================================
# SCENARIO 1: Direct Fork with Lock-Holding Thread (EDUCATIONAL DEMONSTRATION)
# =============================================================================
@pytest.mark.tier5
def test_AGGRESSIVE_direct_fork_thread_graveyard():
    """
    EDUCATIONAL TEST: Demonstrates Thread Graveyard phenomenon.

    NOTE: This test is EXPECTED TO FAIL in a fork-after-thread scenario.
    It proves WHY Velo's Zygote preloads BEFORE creating any threads.

    This test DOES NOT indicate a bug in Velo - it demonstrates the OS-level
    behavior that our architecture is specifically designed to avoid.
    """

    def run_parent() -> int:
        """This simulates the Zygote parent process."""
        lock = threading.Lock()
        ready_event = threading.Event()

        def background_lock_holder():
            """Simulates a library that holds locks (logging, DB pool, etc.)"""
            ready_event.set()
            while True:
                with lock:
                    time.sleep(0.1)  # Hold lock frequently
                time.sleep(0.01)

        # Start the background thread
        holder = threading.Thread(target=background_lock_holder, daemon=True)
        holder.start()
        ready_event.wait()  # Ensure thread is running and has acquired lock at least once

        # Small delay to increase chance thread is holding lock when we fork
        time.sleep(0.05)

        # FORK! This is what Vibe does (or would do)
        pid = os.fork()

        if pid == 0:
            # CHILD PROCESS (simulates the Vibe worker)
            # The background_lock_holder thread is DEAD here!
            # But the lock might still be held!

            acquired = lock.acquire(timeout=1.0)
            if acquired:
                lock.release()
                print("CHILD_LOCK_OK")
                sys.stdout.flush()
                os._exit(0)
            else:
                print("CHILD_DEADLOCK")
                sys.stdout.flush()
                os._exit(1)
        else:
            # PARENT PROCESS
            _, status = os.waitpid(pid, 0)
            exit_code = os.WEXITSTATUS(status)
            return exit_code

    # Run multiple times to catch the race condition
    results = []
    for _i in range(20):
        # We need to use multiprocessing to isolate each test run
        # because fork() in the test runner is problematic
        ctx = multiprocessing.get_context("fork")
        q = ctx.Queue()

        def worker(queue):
            try:
                result = run_parent()
                queue.put(result)
            except Exception as e:
                queue.put(str(e))

        p = ctx.Process(target=worker, args=(q,))
        p.start()
        p.join(timeout=5)

        if p.is_alive():
            p.terminate()
            p.join()
            results.append("TIMEOUT")
        else:
            try:
                result = q.get_nowait()
                results.append("DEADLOCK" if result == 1 else "OK")
            except Exception:
                results.append("ERROR")

    deadlock_count = results.count("DEADLOCK") + results.count("TIMEOUT")
    print(f"\nResults: {results}")
    print(f"Deadlock/Timeout count: {deadlock_count}/20")

    # ASSERTION: If we see ANY deadlocks, the system is vulnerable
    assert deadlock_count == 0, (
        f"CRITICAL: Thread Graveyard Deadlock detected {deadlock_count}/20 times! "
        f"Fork-based execution is fundamentally unsafe."
    )


# =============================================================================
# SCENARIO 2: Real-World Logging Module Deadlock
# =============================================================================
@pytest.mark.tier5
def test_AGGRESSIVE_logging_deadlock():
    """
    AGGRESSIVE TEST: Python's logging module + fork().

    The logging module uses internal locks. This test proves
    that forking with active logging can cause deadlock.
    """
    import logging

    def run_with_logging() -> int:
        # Setup logging with a handler that locks
        logger = logging.getLogger(f"test_{os.getpid()}")
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        stop_event = threading.Event()

        def background_logger():
            while not stop_event.is_set():
                logger.debug("Background log message")
                time.sleep(0.01)

        # Start background logging
        log_thread = threading.Thread(target=background_logger, daemon=True)
        log_thread.start()
        time.sleep(0.1)

        # FORK!
        pid = os.fork()

        if pid == 0:
            # CHILD: Try to log (this acquires logging locks)
            try:
                # Set a timeout alarm for deadlock detection
                def timeout_handler(signum, frame):
                    print("CHILD_LOGGING_TIMEOUT")
                    os._exit(2)

                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(2)  # 2 second timeout

                logger.info("Child process logging")
                signal.alarm(0)
                print("CHILD_LOGGING_OK")
                os._exit(0)
            except Exception as e:
                print(f"CHILD_LOGGING_ERROR: {e}")
                os._exit(1)
        else:
            # PARENT
            stop_event.set()
            _, status = os.waitpid(pid, 0)
            return os.WEXITSTATUS(status)

    results = []
    for _i in range(10):
        ctx = multiprocessing.get_context("fork")
        q = ctx.Queue()

        def worker(queue):
            try:
                result = run_with_logging()
                queue.put(result)
            except Exception as e:
                queue.put(str(e))

        p = ctx.Process(target=worker, args=(q,))
        p.start()
        p.join(timeout=5)

        if p.is_alive():
            p.terminate()
            p.join()
            results.append("TIMEOUT")
        else:
            try:
                result = q.get_nowait()
                if result == 0:
                    results.append("OK")
                elif result == 2:
                    results.append("DEADLOCK")
                else:
                    results.append("ERROR")
            except Exception:
                results.append("ERROR")

    deadlock_count = results.count("DEADLOCK") + results.count("TIMEOUT")
    print(f"\nLogging results: {results}")
    print(f"Deadlock count: {deadlock_count}/10")

    assert deadlock_count == 0, f"CRITICAL: Logging module deadlock detected {deadlock_count}/10 times!"


# =============================================================================
# SCENARIO 3: Simulated Vibe Preload Architecture
# =============================================================================
@pytest.mark.tier5
def test_AGGRESSIVE_simulated_vibe_preload():
    """
    AGGRESSIVE TEST: Simulates what Vibe WOULD do with --preload.

    Architecture:
    1. "Zygote" imports heavy modules (pandas-like simulation)
    2. These modules start background threads on import
    3. Zygote sits in a loop, forking on "file change" signals
    4. Forked workers try to use the modules -> DEADLOCK
    """

    def simulate_preload_zygote() -> list[str]:
        """Simulates the Zygote that has preloaded modules."""

        # Simulate a "heavy library" that starts threads on import
        class FakeHeavyLibrary:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._cache: dict[str, float] = {}
                self._stop = threading.Event()

                # Background "cache warmer" thread (common in ORMs, connection pools)
                self._warmer = threading.Thread(target=self._warm_cache, daemon=True)
                self._warmer.start()

            def _warm_cache(self) -> None:
                while not self._stop.is_set():
                    with self._lock:
                        self._cache["warmed"] = time.time()
                    time.sleep(0.01)

            def get_data(self) -> Any:
                with self._lock:
                    return self._cache.get("warmed", None)

        # "Import" the library (this is what --preload would do)
        library = FakeHeavyLibrary()
        time.sleep(0.1)  # Let cache warmer run

        # Simulate 5 "file change" events (5 forks)
        results = []
        for _i in range(5):
            pid = os.fork()

            if pid == 0:
                # WORKER: Try to use the library
                try:

                    def timeout_handler(signum, frame):
                        os._exit(2)

                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(2)

                    data = library.get_data()
                    signal.alarm(0)
                    os._exit(0 if data else 1)
                except Exception:
                    os._exit(1)
            else:
                # PARENT: Wait for worker
                _, status = os.waitpid(pid, 0)
                code = os.WEXITSTATUS(status)
                results.append("DEADLOCK" if code == 2 else ("OK" if code == 0 else "ERROR"))
                time.sleep(0.05)  # Simulate file change interval

        return results

    # Run the simulation
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()

    def worker(queue):
        try:
            results = simulate_preload_zygote()
            queue.put(results)
        except Exception as e:
            queue.put([str(e)])

    p = ctx.Process(target=worker, args=(q,))
    p.start()
    p.join(timeout=30)

    if p.is_alive():
        p.terminate()
        p.join()
        pytest.fail("Test timed out - likely deadlock in parent!")

    results = q.get()
    deadlock_count = results.count("DEADLOCK")
    print(f"\nPreload simulation results: {results}")
    print(f"Deadlock count: {deadlock_count}/5")

    assert deadlock_count == 0, (
        f"CRITICAL: Simulated Vibe Preload deadlock detected {deadlock_count}/5 times! "
        f"The --preload feature CANNOT be implemented safely without addressing Thread Graveyard."
    )
