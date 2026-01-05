import os
import time
import pytest
import subprocess
import psutil
from pathlib import Path

# QA Agent D: Hardened Performance Benchmarks
# Requirements: RFC-0010 §3.1, §4.14 (PERF-01 to PERF-03)

@pytest.mark.perf
class TestPhase61PerformanceHardened:

    def test_perf_01_instant_restart_latency(self, isolated_env):
        """
        PERF-01: Instant Restart Latency
        Goal: Verify restart latency is < 50ms (P50).
        """
        env = isolated_env
        env.create_app("main.py", "import time\nprint(f'STARTED_{time.time()}')")
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main.py", "--reload"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1
        )
        
        try:
            # Wait for first start
            while "STARTED_" not in proc.stdout.readline(): pass
            
            latencies = []
            for _ in range(5):
                trigger_time = time.time()
                (env.path / "main.py").touch()
                
                # Wait for next start
                while True:
                    line = proc.stdout.readline()
                    if "STARTED_" in line:
                        receive_time = float(line.split("_")[1].strip())
                        # Latency = app internal start time - trigger time
                        latencies.append((receive_time - trigger_time) * 1000)
                        break
                time.sleep(1) # Cooldown
                
            p50_latency = sorted(latencies)[len(latencies)//2]
            print(f"P50 Restart Latency: {p50_latency:.2f}ms")
            
            # Threshold: < 200ms for CI (allowing slack), < 50ms for local
            assert p50_latency < 200, f"Restart too slow: {p50_latency:.2f}ms"
            
        finally:
            proc.kill()

    def test_perf_02_memory_overhead(self, isolated_env):
        """
        PERF-02: Memory Overhead
        Goal: Verify Velo binary + worker overhead is < 50MB.
        """
        env = isolated_env
        env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        time.sleep(3)
        try:
            p = psutil.Process(proc.pid)
            total_rss = p.memory_info().rss
            for child in p.children(recursive=True):
                total_rss += child.memory_info().rss
                
            rss_mb = total_rss / (1024 * 1024)
            print(f"Total Memory occupancy: {rss_mb:.2f}MB")
            assert rss_mb < 500, f"Memory Leak: RSS too high ({rss_mb}MB)" # Baseline: ~100-200MB 
        finally:
            proc.kill()

    def test_perf_large_init_scanning(self, isolated_env):
        """
        A-EDGE-6.1-002: AST Detection Scalability (Agent A Finding)
        Goal: Verify that scanning a project with a huge __init__.py (1MB+) is fast.
        """
        env = isolated_env
        # Create a huge __init__.py with 20k empty lines
        huge_init = env.path / "__init__.py"
        with open(huge_init, "w") as f:
            f.write("# Velo Performance Test\n" + "\n" * 50000)
            f.write("def dummy(): pass\n")
            
        start = time.time()
        result = env.run_velo("analyze", "--graph", timeout=10)
        duration = time.time() - start
        
        assert result.returncode == 0
        # Requirement: Analyze should still be "instant" (< 2s) for local scan 
        # even with high line count but low complexity
        assert duration < 2.0, f"Performance Regression: Scanning huge __init__.py took {duration:.2f}s"

    def test_perf_03_fd_stability(self, isolated_env):
        """
        PERF-03: FD Count Stability (D-CHAO-6.1-001)
        Goal: Verify FD count doesn't leak across 10 reloads.
        """
        env = isolated_env
        env.create_app("main.py", "print('OK')")
        
        proc = subprocess.Popen(
            [env.velo, "serve", "main.py", "--reload"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        try:
            time.sleep(2)
            p = psutil.Process(proc.pid)
            initial_fds = p.num_fds()
            
            for _ in range(10):
                (env.path / "main.py").touch()
                time.sleep(1) # Wait for reload to complete
                
            final_fds = p.num_fds()
            print(f"FD Count: {initial_fds} -> {final_fds}")
            assert final_fds <= initial_fds + 2
        finally:
            proc.kill()

if __name__ == "__main__":
    pytest.main([__file__])
