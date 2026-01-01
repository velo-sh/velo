"""
Velo QA: Phase 3 Rigorous Performance Tests
============================================
Statistical performance testing with P50/P95/P99 metrics.

Why rigorous testing:
- Min values hide outliers
- P95/P99 matter for user experience
- Must warm up before measuring
"""

import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest


def get_velo_binary():
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class PerfEnv:
    """Environment for performance testing."""
    
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="perf_"))
        self.velo = get_velo_binary()
    
    def setup(self):
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, capture_output=True)
        (self.path / "uv.lock").write_text("{}")
        return self
    
    def run_timed(self, args, timeout=30) -> tuple:
        """Run and return (code, duration_ms)."""
        start = time.perf_counter()
        result = subprocess.run(
            [self.velo] + args,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        duration = (time.perf_counter() - start) * 1000
        return result.returncode, duration, result.stderr
    
    def create_script(self, name, content):
        (self.path / name).write_text(content)
    
    def warmup(self, script, count=10):
        """Warm up Zygote before measurements."""
        for _ in range(count):
            self.run_timed(["run", "--zygote", script], timeout=10)
    
    def cleanup(self):
        subprocess.run(["pkill", "-f", "velo_zygote"], capture_output=True)
        try:
            shutil.rmtree(self.path)
        except:
            pass
    
    def __enter__(self):
        return self.setup()
    
    def __exit__(self, *args):
        self.cleanup()


def percentile(data, p):
    """Calculate percentile."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def print_stats(times, label=""):
    """Print statistical summary."""
    if not times:
        print(f"  {label}: No data")
        return
    
    p50 = percentile(times, 50)
    p95 = percentile(times, 95)
    p99 = percentile(times, 99)
    
    print(f"\n  {label} Statistics ({len(times)} samples):")
    print(f"    Min:  {min(times):.1f}ms")
    print(f"    P50:  {p50:.1f}ms")
    print(f"    P95:  {p95:.1f}ms")
    print(f"    P99:  {p99:.1f}ms")
    print(f"    Max:  {max(times):.1f}ms")
    print(f"    Avg:  {statistics.mean(times):.1f}ms")
    print(f"    StdDev: {statistics.stdev(times) if len(times) > 1 else 0:.1f}ms")


class TestRigorousPerformance:
    """Rigorous performance tests with statistical analysis."""

    def test_perf_101_warm_p95_under_20ms(self):
        """
        PERF-101: P95 warm start should be under 20ms.
        
        RFC target: < 50ms
        Stretch goal: < 20ms for P95
        """
        with PerfEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            # Warm up
            env.warmup("quick.py", count=10)
            
            # Measure 50 runs
            times = []
            for _ in range(50):
                code, duration, stderr = env.run_timed(["run", "--zygote", "quick.py"])
                if code == 0 and "Falling back" not in stderr:
                    times.append(duration)
            
            print_stats(times, "Warm Start")
            
            assert len(times) >= 40, f"Too many failures: only {len(times)}/50 succeeded"
            
            p95 = percentile(times, 95)
            assert p95 < 20, f"P95 warm start too slow: {p95:.1f}ms > 20ms"

    def test_perf_102_fork_p99_under_15ms(self):
        """
        PERF-102: P99 fork latency should be under 15ms.
        
        RFC target: < 5ms (Min)
        Realistic P99: < 15ms
        """
        with PerfEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            # Warm up more aggressively
            env.warmup("quick.py", count=20)
            
            # Measure 100 runs
            times = []
            for _ in range(100):
                code, duration, stderr = env.run_timed(["run", "--zygote", "quick.py"])
                if code == 0 and "Falling back" not in stderr:
                    times.append(duration)
            
            print_stats(times, "Fork Latency")
            
            assert len(times) >= 80, f"Too many failures: only {len(times)}/100 succeeded"
            
            p99 = percentile(times, 99)
            assert p99 < 15, f"P99 fork latency too slow: {p99:.1f}ms > 15ms"

    def test_perf_103_no_outliers(self):
        """
        PERF-103: Max should not exceed 3x of P50.
        
        Outliers indicate instability.
        """
        with PerfEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            env.warmup("quick.py", count=10)
            
            times = []
            for _ in range(50):
                code, duration, stderr = env.run_timed(["run", "--zygote", "quick.py"])
                if code == 0 and "Falling back" not in stderr:
                    times.append(duration)
            
            print_stats(times, "Outlier Check")
            
            if len(times) >= 40:
                p50 = percentile(times, 50)
                max_time = max(times)
                ratio = max_time / p50
                
                print(f"    Max/P50 ratio: {ratio:.1f}x")
                
                assert ratio < 3, f"Too many outliers: Max ({max_time:.1f}ms) is {ratio:.1f}x of P50 ({p50:.1f}ms)"

    def test_perf_104_consistent_under_load(self):
        """
        PERF-104: Performance stays consistent under parallel load.
        
        10 concurrent runs, all should complete under 100ms.
        """
        with PerfEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            env.warmup("quick.py", count=10)
            
            times = []
            errors = []
            lock = threading.Lock()
            
            def run_one():
                try:
                    code, duration, stderr = env.run_timed(["run", "--zygote", "quick.py"], timeout=10)
                    with lock:
                        if code == 0:
                            times.append(duration)
                        else:
                            errors.append(f"code={code}")
                except Exception as e:
                    with lock:
                        errors.append(str(e))
            
            # Run 10 concurrent
            threads = [threading.Thread(target=run_one) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            
            print_stats(times, "Concurrent (10)")
            print(f"    Errors: {len(errors)}")
            
            assert len(times) >= 7, f"Too many concurrent failures: only {len(times)}/10 succeeded"
            assert max(times) < 100, f"Concurrent max too slow: {max(times):.1f}ms > 100ms"

    def test_perf_105_zygote_vs_normal_speedup(self):
        """
        PERF-105: Zygote should be faster than normal run.
        
        RFC claim: ~49x speedup
        Minimum acceptable: 5x
        """
        with PerfEnv() as env:
            env.create_script("quick.py", 'print("ok")')
            
            # Normal runs (without Zygote)
            normal_times = []
            for _ in range(5):
                code, duration, _ = env.run_timed(["run", "quick.py"])  # No --zygote
                if code == 0:
                    normal_times.append(duration)
            
            # Zygote warm runs
            env.warmup("quick.py", count=5)
            zygote_times = []
            for _ in range(10):
                code, duration, stderr = env.run_timed(["run", "--zygote", "quick.py"])
                if code == 0 and "Falling back" not in stderr:
                    zygote_times.append(duration)
            
            if normal_times and zygote_times:
                normal_avg = statistics.mean(normal_times)
                zygote_avg = statistics.mean(zygote_times)
                speedup = normal_avg / zygote_avg
                
                print(f"\n  Zygote vs Normal Speedup:")
                print(f"    Normal avg: {normal_avg:.1f}ms")
                print(f"    Zygote avg: {zygote_avg:.1f}ms")
                print(f"    Speedup: {speedup:.1f}x")
                
                assert speedup >= 5, f"Speedup too low: {speedup:.1f}x < 5x"
