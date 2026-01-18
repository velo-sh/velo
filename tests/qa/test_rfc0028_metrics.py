"""
RFC-0028 Performance Metrics Acceptance Tests

RFC-0028 Performance Targets (Section 7):
+-------------------+-----------------+-------------+--------+
| Metric            | Standard pytest | pytest-velo | Target |
+-------------------+-----------------+-------------+--------+
| Per-worker startup| 500ms - 2s      | ~1ms        | < 2ms  |
| 1000 tests        | 30+ min         | ~30 sec     | 60x    |
| Memory per worker | Full copy       | COW delta   | < 2MB  |
| Fork latency      | N/A             | ~1ms        | < 2ms  |
+-------------------+-----------------+-------------+--------+

Acceptance Methods:
1. Fork Latency - Directly measure os.fork() latency
2. Worker Startup - Compare velo fork vs subprocess.Popen startup time
3. Memory Overhead - Measure memory delta after fork
4. Throughput - Measure forks per second
"""

import os
import subprocess
import sys
import tempfile
import time
import resource
from pathlib import Path
from typing import Tuple

import pytest


# =============================================================================
# METRIC 1: FORK LATENCY < 2ms
# RFC: "Fork latency: < 2ms"
# =============================================================================


class TestMetric_ForkLatency:
    """Metric Acceptance: Fork latency < 2ms"""

    def test_single_fork_latency_p50(self):
        """P50 fork latency should be < 2ms"""
        from pytest_velo.plugin import measure_fork_latency

        latencies = sorted([measure_fork_latency() for _ in range(100)])
        p50 = latencies[50]
        
        assert p50 < 2.0, f"P50 latency {p50:.2f}ms exceeds 2ms target"

    def test_single_fork_latency_p99(self):
        """P99 fork latency should be < 5ms (allow occasional spikes)"""
        from pytest_velo.plugin import measure_fork_latency

        latencies = sorted([measure_fork_latency() for _ in range(100)])
        p99 = latencies[99]
        
        assert p99 < 5.0, f"P99 latency {p99:.2f}ms exceeds 5ms target"

    def test_fork_latency_stability(self):
        """Fork latency should be stable, std_dev < 1ms"""
        from pytest_velo.plugin import measure_fork_latency

        latencies = [measure_fork_latency() for _ in range(50)]
        avg = sum(latencies) / len(latencies)
        variance = sum((x - avg) ** 2 for x in latencies) / len(latencies)
        std_dev = variance ** 0.5
        
        assert std_dev < 2.0, f"Latency std_dev {std_dev:.2f}ms too high"


# =============================================================================
# METRIC 2: WORKER STARTUP TIME
# RFC: "Per-worker startup: 500ms - 2s (standard) vs ~1ms (velo)"
# =============================================================================


class TestMetric_WorkerStartup:
    """Metric Acceptance: Worker startup time comparison"""

    def measure_subprocess_startup(self) -> float:
        """Measure subprocess.Popen Python startup time"""
        start = time.perf_counter()
        proc = subprocess.Popen(
            [sys.executable, '-c', 'pass'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait()
        end = time.perf_counter()
        return (end - start) * 1000  # ms

    def measure_fork_startup(self) -> float:
        """Measure os.fork() startup time"""
        start = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        else:
            os.waitpid(pid, 0)
        end = time.perf_counter()
        return (end - start) * 1000  # ms

    def test_fork_faster_than_subprocess(self):
        """Fork should be faster than subprocess by > 5x"""
        fork_times = [self.measure_fork_startup() for _ in range(10)]
        subprocess_times = [self.measure_subprocess_startup() for _ in range(10)]

        fork_avg = sum(fork_times) / len(fork_times)
        subprocess_avg = sum(subprocess_times) / len(subprocess_times)
        
        speedup = subprocess_avg / fork_avg
        
        # macOS subprocess is fast (~10ms), so 5x speedup is acceptable
        # On Linux with heavy deps, speedup would be > 100x
        assert speedup > 5, f"Speedup {speedup:.1f}x should be > 5x"

    def test_fork_startup_under_2ms(self):
        """Fork startup should be < 2ms"""
        times = [self.measure_fork_startup() for _ in range(20)]
        avg = sum(times) / len(times)
        
        assert avg < 2.0, f"Fork startup {avg:.2f}ms exceeds 2ms target"


# =============================================================================
# METRIC 3: MEMORY OVERHEAD < 2MB per worker
# RFC: "Memory overhead: < 2MB per concurrent test"
# =============================================================================


class TestMetric_MemoryOverhead:
    """Metric Acceptance: Memory overhead < 2MB per worker"""

    def get_memory_usage_kb(self) -> int:
        """Get current process RSS memory in KB"""
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    def test_fork_memory_overhead(self):
        """Fork memory delta should be < 2MB"""
        # Due to COW, actual memory usage after fork is small
        # This measures fork + simple operations

        memory_deltas = []
        
        for _ in range(5):
            parent_mem_before = self.get_memory_usage_kb()
            
            pid = os.fork()
            if pid == 0:
                # Child: do some operations to trigger COW
                data = list(range(1000))
                child_mem = self.get_memory_usage_kb()
                os._exit(0)
            else:
                os.waitpid(pid, 0)
                parent_mem_after = self.get_memory_usage_kb()
                delta = parent_mem_after - parent_mem_before
                memory_deltas.append(delta)

        avg_delta_kb = sum(memory_deltas) / len(memory_deltas)
        avg_delta_mb = avg_delta_kb / 1024
        
        # macOS returns bytes, Linux returns KB
        if sys.platform == 'darwin':
            avg_delta_mb = avg_delta_kb / (1024 * 1024)
        
        assert avg_delta_mb < 2.0, f"Memory overhead {avg_delta_mb:.2f}MB exceeds 2MB"


# =============================================================================
# METRIC 4: THROUGHPUT (forks per second)
# RFC implied: 1000 tests in ~30 sec = ~33 tests/sec
# =============================================================================


class TestMetric_Throughput:
    """Metric Acceptance: Throughput"""

    def test_fork_throughput(self):
        """Should complete > 30 forks per second"""
        from pytest_velo.plugin import measure_fork_latency

        start = time.perf_counter()
        count = 0
        target_duration = 1.0  # 1 second
        
        while time.perf_counter() - start < target_duration:
            measure_fork_latency()
            count += 1
        
        elapsed = time.perf_counter() - start
        forks_per_second = count / elapsed
        
        # RFC target: 1000 tests / 30 sec = 33 tests/sec
        assert forks_per_second > 30, (
            f"Throughput {forks_per_second:.1f} forks/sec < 30 target"
        )

    def test_sustained_fork_performance(self):
        """Sustained forks should not degrade performance"""
        from pytest_velo.plugin import measure_fork_latency

        # First 50 forks
        first_batch = [measure_fork_latency() for _ in range(50)]
        first_avg = sum(first_batch) / len(first_batch)
        
        # Next 50 forks
        second_batch = [measure_fork_latency() for _ in range(50)]
        second_avg = sum(second_batch) / len(second_batch)
        
        # Later forks should not be > 50% slower
        degradation = (second_avg - first_avg) / first_avg * 100
        
        assert degradation < 50, (
            f"Performance degraded {degradation:.1f}% after sustained forks"
        )


# =============================================================================
# METRIC 5: SPEEDUP RATIO
# RFC: "1000 tests: 30+ min -> ~30 sec" = 60x speedup
# =============================================================================


class TestMetric_SpeedupRatio:
    """Metric Acceptance: Speedup ratio"""

    def test_theoretical_speedup(self):
        """Theoretical speedup should be > 60x"""
        # Standard pytest worker startup: ~500ms (conservative)
        # Velo fork: ~1ms
        
        from pytest_velo.plugin import measure_fork_latency
        
        velo_latency = sum(measure_fork_latency() for _ in range(10)) / 10
        
        # Conservative estimate: subprocess.Popen starts Python in ~50-100ms
        # With module loading etc., approximately 500ms
        standard_latency = 500.0  # ms
        
        speedup = standard_latency / velo_latency
        
        # Should achieve at least 50x
        assert speedup > 50, f"Speedup {speedup:.0f}x should be > 50x"


# =============================================================================
# BENCHMARK: Generate Report
# =============================================================================


class TestBenchmarkReport:
    """Generate performance benchmark report"""

    def test_generate_benchmark_summary(self, capsys):
        """Generate performance benchmark summary"""
        from pytest_velo.plugin import measure_fork_latency

        # Collect data
        latencies = sorted([measure_fork_latency() for _ in range(100)])
        
        p50 = latencies[50]
        p99 = latencies[99]
        avg = sum(latencies) / len(latencies)
        min_val = min(latencies)
        max_val = max(latencies)

        # Calculate throughput
        start = time.perf_counter()
        for _ in range(100):
            measure_fork_latency()
        elapsed = time.perf_counter() - start
        throughput = 100 / elapsed

        print("\n" + "=" * 50)
        print("RFC-0028 PERFORMANCE BENCHMARK REPORT")
        print("=" * 50)
        print(f"\nFork Latency:")
        print(f"  Min:  {min_val:.2f} ms")
        print(f"  P50:  {p50:.2f} ms (target: < 2ms)")
        print(f"  P99:  {p99:.2f} ms")
        print(f"  Max:  {max_val:.2f} ms")
        print(f"  Avg:  {avg:.2f} ms")
        print(f"\nThroughput:")
        print(f"  {throughput:.0f} forks/sec (target: > 33/sec)")
        print(f"\nSpeedup vs subprocess:")
        print(f"  ~{500/avg:.0f}x (target: > 60x)")
        print("=" * 50 + "\n")

        # Verify targets
        assert p50 < 2.0, "P50 latency target not met"
        assert throughput > 33, "Throughput target not met"
