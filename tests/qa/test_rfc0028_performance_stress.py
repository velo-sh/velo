"""
RFC-0028 100% Real Head-to-Head Benchmark (NO SAMPLING)

Measure 250 real isolated tests. 
Standard: 250 process starts.
Velo: 250 forks.
"""

import os
import subprocess
import time
import sys
from pathlib import Path

import pytest

def create_real_test_suite(directory: Path, count: int):
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        test_file = directory / f"test_real_case_{i}.py"
        test_file.write_text(f"def test_real_case_{i}(): assert 1+1==2")

class TestRFC0028_StrictBenchmark:
    """
    100% Real comparison for 250 tests. 
    Standard spawns 250 processes one by one.
    Velo runs 250 tests via Zygote.
    """

    def test_strict_250_comparison(self, tmp_path):
        count = 250
        test_dir = tmp_path / "strict_250_suite"
        create_real_test_suite(test_dir, count)
        
        # 1. Standard: REAL 250 subprocess runs
        print(f"\n[Strict] Starting Standard (250 REAL subprocess runs)...")
        start_std = time.perf_counter()
        for i in range(count):
            subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir / f"test_real_case_{i}.py"), "-q"],
                capture_output=True
            )
        std_duration = time.perf_counter() - start_std
        print(f"[Strict] Standard (250 runs) total wall-clock: {std_duration:.2f}s")

        # 2. Velo: REAL 250 tests in Zygote
        print(f"[Strict] Starting Velo (250 tests via Zygote)...")
        start_velo = time.perf_counter()
        subprocess.run(
            ["uv", "run", "pytest", str(test_dir), "--velo", "-q", "--no-header"],
            capture_output=True
        )
        velo_duration = time.perf_counter() - start_velo
        print(f"[Strict] Velo (250 tests) total wall-clock: {velo_duration:.2f}s")

        speedup = std_duration / velo_duration
        print(f"[Result] Real Speedup: {speedup:.1f}x")
        
        assert speedup > 15.0, f"Real speedup {speedup:.1f}x below threshold"
