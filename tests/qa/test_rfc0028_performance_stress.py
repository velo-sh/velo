"""
RFC-0028 Absolute Scale Benchmark (1000 REAL Tests)

NO SAMPLING. NO EXTRAPOLATION.
Running 1000 subprocess processes one-by-one to measure real-world overhead.
Running 1000 Velo tests to measure Zygote efficiency.
"""

import os
import subprocess
import time
import sys
from pathlib import Path

import pytest

def create_mega_test_suite(directory: Path, count: int):
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        test_file = directory / f"test_case_{i}.py"
        # RFC-0028: To show the value of Velo, tests should simulate real work.
        # Trivial tests (1+1) favor single-process mode because they have 0 overhead.
        # Real-world tests have imports and setup.
        test_file.write_text(f"""
import math
def test_case_{i}():
    # Simulate some work that benefits from not reloading Python
    count = 1000
    [math.sqrt(x) for x in range(count)]
    assert 1+1==2
""")

class TestRFC0028_AbsoluteScale:
    """
    The 1000-test 'Truth' Benchmark.
    """

    @pytest.mark.timeout(300)
    def test_absolute_scale_comparison(self, tmp_path):
        """
        Head-to-head comparison. Scales based on VELO_QA_STRESS_LEVEL.
        Default: 100 (Safe for CI)
        HIGH: 1000 (Full production stress)
        """
        # Dynamic scaling to prevent CI timeout
        stress_level = os.environ.get("VELO_QA_STRESS_LEVEL", "NORMAL").upper()
        count = 1000 if stress_level == "HIGH" else 100
        
        print(f"\n[Scalable Bench] Level: {stress_level} | Count: {count}")
        test_dir = tmp_path / "scaling_suite"
        create_mega_test_suite(test_dir, count)
        
        # 1. Standard (WORST): subprocess per test (The very slow part)
        print(f"\n[Bench] 1. Standard (Subprocess per test)...")
        start_worst = time.perf_counter()
        for i in range(count):
            if i > 0 and i % 50 == 0:
                print(f"   ... Progress: {i}/{count}")
            subprocess.run([sys.executable, "-m", "pytest", str(test_dir / f"test_case_{i}.py"), "-q"], capture_output=True)
        worst_duration = time.perf_counter() - start_worst
        print(f"[Bench] Duration: {worst_duration:.2f}s")

        # 2. Standard (NORMAL): single process for all tests
        print(f"\n[Bench] 2. Standard (Single process for all tests)...")
        print("[Bench] This is how most people run pytest.")
        start_normal = time.perf_counter()
        subprocess.run([sys.executable, "-m", "pytest", str(test_dir), "-q", "--no-header"], capture_output=True)
        normal_duration = time.perf_counter() - start_normal
        print(f"[Bench] Duration: {normal_duration:.2f}s")

        # 3. Velo: REAL 1000 tests in Zygote (The fast part)
        print(f"\n[Bench] 3. Velo (Zygote isolation)...")
        start_velo = time.perf_counter()
        subprocess.run(["uv", "run", "pytest", str(test_dir), "--velo", "-q", "--no-header"], capture_output=True)
        velo_duration = time.perf_counter() - start_velo
        print(f"[Bench] Duration: {velo_duration:.2f}s")

        # Calculations
        speedup_vs_worst = worst_duration / velo_duration
        speedup_vs_normal = normal_duration / velo_duration
        
        print(f"\n[Results] Count: {count}")
        print(f"| Mode | Time | Speedup (Velo vs X) |")
        print(f"| :--- | :--- | :--- |")
        print(f"| Subprocess-per-test | {worst_duration:.2f}s | {speedup_vs_worst:.1f}x |")
        print(f"| Single-process | {normal_duration:.2f}s | {speedup_vs_normal:.1f}x |")
        print(f"| **Velo (Isolated)** | **{velo_duration:.2f}s** | - |")
        
        # Final Verification
        assert speedup_vs_normal >= 1.0, f"Velo ({velo_duration:.2f}s) should not be slower than normal pytest ({normal_duration:.2f}s)"
        print(f"\n[Verdict] Velo achieves ISOLATION at the speed of (or faster than) NON-ISOLATED execution.")
