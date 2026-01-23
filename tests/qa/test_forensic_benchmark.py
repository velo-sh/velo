"""
Velo Forensic Benchmark Runner
Measures 'Absolute Truth' across 3 modes with Cold Start enforcement.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
BENCH_ROOT = BASE_DIR / "tests" / "qa" / "forensic_benchmarks"
CACHE_BUSTER = BASE_DIR / "scripts" / "qa" / "cache_buster.py"


def bust_cache(target_path: Path) -> None:
    print(f"\n❄️  Busting OS Cache for {target_path}...")
    subprocess.run([sys.executable, str(CACHE_BUSTER), str(target_path)], check=True)
    # Wait for OS to settle
    time.sleep(2)


def run_bench(cmd: list[str], env: dict[str, str], label: str) -> tuple[float, str]:
    print(f"🏃 Running {label}...")
    start = time.perf_counter()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    duration = time.perf_counter() - start

    # Extract "collected X items" as a proxy for collection time if possible
    # but wall-clock is our primary metric for "Cold Start" reality
    return duration, result.stdout


class TestVeloForensic:
    """
    The Scientific Truth: Cold-Start Benchmarking.
    """

    @pytest.mark.parametrize("count", [100, 200])
    def test_forensic_comparison(self, count):
        project_dir = BENCH_ROOT / f"gold_{count}"
        if not project_dir.exists():
            pytest.skip(f"Project tier {count} not found at {project_dir}")

        test_dir = project_dir / "tests"
        src_dir = project_dir / "src"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
        # Ensure velo is in PATH
        velo_bin = BASE_DIR / "target" / "release"
        env["PATH"] = str(velo_bin) + os.pathsep + env.get("PATH", "")

        results = {}

        # 1. Mode: Standard Single Process (Unsafe)
        bust_cache(project_dir)
        duration, output = run_bench(
            [sys.executable, "-m", "pytest", str(test_dir), "-q", "--no-header"], env, "Standard Single Process"
        )
        results["Single-Process"] = duration
        print(f"   ⏱️  Duration: {duration:.2f}s")

        # 2. Mode: Standard Subprocess Isolation (Safe but Slow)
        bust_cache(project_dir)
        print("🏃 Running Subprocess Isolation (Subprocess per test)...")
        start_sub = time.perf_counter()
        test_files = list(test_dir.rglob("test_forensic_*.py"))
        for i, f in enumerate(test_files):
            subprocess.run([sys.executable, "-m", "pytest", str(f), "-q"], env=env, capture_output=True)
            if (i + 1) % 50 == 0:
                print(f"   ... Progress: {i + 1}/{count}")
        duration_sub = time.perf_counter() - start_sub
        results["Subprocess-Isolated"] = duration_sub
        print(f"   ⏱️  Duration: {duration_sub:.2f}s")

        # 3. Mode: Velo Zygote Isolation (Safe and Optimized)
        bust_cache(project_dir)
        duration_velo, output_velo = run_bench(
            ["pytest", str(test_dir), "--velo", "-q", "--no-header"], env, "Velo Zygote"
        )
        results["Velo-Isolated"] = duration_velo
        print(f"   ⏱️  Duration: {duration_velo:.2f}s")

        # Summary Table
        print(f"\n📊 FINAL FORENSIC RESULTS ({count} Tests)")
        print("-" * 50)
        print("| Mode                 | Wall-Clock Time | Rel. Speed |")
        print("| :------------------- | :-------------- | :--------- |")
        print(f"| Subprocess-Isolated  | {results['Subprocess-Isolated']:>14.2f}s | 1.0x (Ref) |")
        print(
            f"| Single-Process       | {results['Single-Process']:>14.2f}s | {results['Subprocess-Isolated'] / results['Single-Process']:>9.1f}x |"
        )
        print(
            f"| **Velo-Isolated**    | {results['Velo-Isolated']:>14.2f}s | {results['Subprocess-Isolated'] / results['Velo-Isolated']:>9.1f}x |"
        )
        print("-" * 50)

        # Sanity check: Velo should be faster than Subprocess Isolation
        assert results["Velo-Isolated"] < results["Subprocess-Isolated"]
