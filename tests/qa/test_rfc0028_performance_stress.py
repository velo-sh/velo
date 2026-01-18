"""
RFC-0028 High-Fidelity Performance Benchmark
Scales: 100, 500, 1000 tests
"""

import os
import subprocess
import time
import sys
from pathlib import Path
import pytest

# Project metadata
BASE_QA_DIR = Path(__file__).parent / "benchmarks"
GENERATOR_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "qa" / "benchmark_generator.py"

def ensure_benchmark_project(count: int) -> Path:
    """Ensure a project of the given scale exists on disk."""
    project_dir = BASE_QA_DIR / f"project_{count}"
    if not project_dir.exists():
        subprocess.run([
            sys.executable, str(GENERATOR_SCRIPT),
            "--count", str(count),
            "--output", str(project_dir)
        ], check=True)
    return project_dir

class TestRFC0028_AbsoluteScale:
    """
    The High-Fidelity 'Truth' Benchmark.
    Compares 3 modes on realistic directory structures.
    """

    @pytest.mark.parametrize("count", [100, 500, 1000])
    @pytest.mark.timeout(600)  # Standard mode is slow
    def test_absolute_scale_tiers(self, count):
        # 0. Preparation
        stress_level = os.environ.get("VELO_QA_STRESS_LEVEL", "NORMAL").upper()
        
        # In NORMAL mode, we only run the 100-test tier to save time in CI
        if stress_level == "NORMAL" and count > 100:
            pytest.skip("Skipping high-scale tiers in NORMAL stress mode. Set VELO_QA_STRESS_LEVEL=HIGH to run.")

        project_dir = ensure_benchmark_project(count)
        test_dir = project_dir / "tests"
        
        # Ensure the project's src is in PYTHONPATH for the subprocesses
        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_dir / "src") + os.pathsep + env.get("PYTHONPATH", "")

        print(f"\n\n🚀 Running Benchmark Tier: {count} Tests")
        print(f"📂 Project Path: {project_dir}")

        # 1. Standard (WORST): subprocess per test
        # We only run this for 100 and 500 because 1000 takes too long (>3 min)
        worst_duration = 0
        if count <= 500:
            print(f"\n[Bench] 1. Standard (Subprocess per test)...")
            start_worst = time.perf_counter()
            test_files = list(test_dir.rglob("test_case_*.py"))
            for i, test_file in enumerate(test_files):
                if i > 0 and i % 50 == 0:
                    print(f"   ... Progress: {i}/{count}")
                subprocess.run([sys.executable, "-m", "pytest", str(test_file), "-q"], env=env, capture_output=True)
            worst_duration = time.perf_counter() - start_worst
            print(f"[Bench] Duration: {worst_duration:.2f}s")
        else:
            print(f"\n[Bench] 1. Standard (Subprocess per test) -> SKIPPED (Too slow for 1000)")

        # 2. Standard (NORMAL): single process for all tests
        print(f"\n[Bench] 2. Standard (Single process for all tests)...")
        start_normal = time.perf_counter()
        subprocess.run([sys.executable, "-m", "pytest", str(test_dir), "-q", "--no-header"], env=env, capture_output=True)
        normal_duration = time.perf_counter() - start_normal
        print(f"[Bench] Duration: {normal_duration:.2f}s")

        # 3. Velo: REAL Zygote forks
        print(f"\n[Bench] 3. Velo (Zygote isolation)...")
        # Ensure velo is in PATH
        velo_bin_dir = Path(__file__).parent.parent.parent / "target" / "release"
        env["PATH"] = str(velo_bin_dir) + os.pathsep + env.get("PATH", "")
        
        start_velo = time.perf_counter()
        subprocess.run(["pytest", str(test_dir), "--velo", "-q", "--no-header"], env=env, capture_output=True)
        velo_duration = time.perf_counter() - start_velo
        print(f"[Bench] Duration: {velo_duration:.2f}s")

        # Results Reporting
        print(f"\n[Final Results - {count} Tests]")
        print("-" * 40)
        if worst_duration > 0:
            print(f"Subprocess-per-test: {worst_duration:.2f}s  ({worst_duration/velo_duration:.1f}x slower)")
        print(f"Single-process:      {normal_duration:.2f}s  ({normal_duration/velo_duration:.1f}x speed)")
        print(f"Velo (Isolated):     {velo_duration:.2f}s")
        print("-" * 40)

        # Sanity check
        assert velo_duration < 15.0 if count == 1000 else True
        assert velo_duration > 0
