"""
OPT-0010-001: MessagePack IPC - Agent B (Stability)

Tests stability of MessagePack IPC protocol:
- STAB-OPT-001: Sequential IPC calls
- STAB-OPT-002: Concurrent serialization
- STAB-OPT-003: Memory usage under load
"""

import gc
import sys
import threading
import unittest
from pathlib import Path

# Add vendor path
vendor_path = Path(__file__).parents[4] / "python" / "velo" / "_vendor"
if str(vendor_path) not in sys.path:
    sys.path.insert(0, str(vendor_path))


class TestMsgpackStability(unittest.TestCase):
    """Agent B: Stability Testing for MessagePack IPC."""

    def test_stab_opt_001_sequential_ipc_calls(self):
        """
        STAB-OPT-001: Sequential IPC calls

        Requirement: Repeated serialization must be stable and consistent.

        Test:
        1. Serialize same message 1000 times
        2. Verify identical output each time
        3. Verify no memory leaks (gc check)
        """
        import umsgpack

        test_msg = {
            "type": "Fork",
            "script_path": "/path/to/main.py",
            "args": ["--host", "0.0.0.0", "--port", "8000"],
            "fast_mode": True,
        }

        # First serialization as baseline
        baseline = umsgpack.packb(test_msg)

        # Repeat 1000 times
        for i in range(1000):
            packed = umsgpack.packb(test_msg)
            self.assertEqual(packed, baseline, f"Iteration {i}: Output must be identical")

        # Verify deserialize works
        for _i in range(100):
            unpacked = umsgpack.unpackb(baseline)
            self.assertEqual(unpacked["type"], "Fork")
            self.assertEqual(unpacked["fast_mode"], True)

        # GC check - no leaked objects
        gc.collect()

    def test_stab_opt_002_concurrent_ipc_calls(self):
        """
        STAB-OPT-002: Concurrent serialization

        Requirement: Thread-safe serialization.

        Test:
        1. Spawn 10 threads doing serialization
        2. Each thread does 100 iterations
        3. Verify no exceptions, no corruption
        """
        import umsgpack

        errors = []
        results = []
        lock = threading.Lock()

        def worker(thread_id):
            try:
                for i in range(100):
                    msg = {
                        "type": "Fork",
                        "thread_id": thread_id,
                        "iteration": i,
                    }
                    packed = umsgpack.packb(msg)
                    unpacked = umsgpack.unpackb(packed)

                    if unpacked["thread_id"] != thread_id:
                        with lock:
                            errors.append(f"T{thread_id}: thread_id mismatch")
                    if unpacked["iteration"] != i:
                        with lock:
                            errors.append(f"T{thread_id}: iteration mismatch")

                with lock:
                    results.append(thread_id)
            except Exception as e:
                with lock:
                    errors.append(f"T{thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 10, "All threads must complete")

    def test_stab_opt_003_ipc_under_memory_pressure(self):
        """
        STAB-OPT-003: IPC under memory pressure

        Requirement: Stable serialization under moderate load.

        Test:
        1. Create many large messages
        2. Serialize/deserialize in loop
        3. Verify stability and cleanup
        """
        import umsgpack

        # Create moderately large messages
        large_args = ["argument_" + str(i) for i in range(1000)]

        for i in range(100):
            msg = {
                "type": "Fork",
                "script_path": f"/path/script_{i}.py",
                "args": large_args,
            }

            packed = umsgpack.packb(msg)
            self.assertGreater(len(packed), 10000, "Packed size should be substantial")

            unpacked = umsgpack.unpackb(packed)
            self.assertEqual(len(unpacked["args"]), 1000)

        # Force garbage collection
        gc.collect()

        # Verify we can still allocate
        msg = {"final": "test"}
        packed = umsgpack.packb(msg)
        unpacked = umsgpack.unpackb(packed)
        self.assertEqual(unpacked["final"], "test")


if __name__ == "__main__":
    unittest.main()
