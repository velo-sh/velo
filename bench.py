#!/usr/bin/env python3
"""
Velo Benchmark: Microsecond-precision startup time comparison.

Compares:
- CPython cold start
- Velo cold start
- Velo cached start (after warmup)
"""

import subprocess
import sys
import time
import statistics
from pathlib import Path

VELO_BIN = "./target/release/velo"
TEST_SCRIPT = "tests/corpus/hello.py"
ITERATIONS = 10
WARMUP_RUNS = 2


def measure_startup(cmd: list[str], iterations: int = ITERATIONS) -> list[float]:
    """Measure startup time in milliseconds."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True)
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        if result.returncode == 0:
            times.append(elapsed)
    return times


def print_stats(name: str, times: list[float]):
    """Print statistics for a measurement."""
    if not times:
        print(f"  {name}: No successful runs")
        return
    
    avg = statistics.mean(times)
    median = statistics.median(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0
    min_t = min(times)
    max_t = max(times)
    
    print(f"  {name}:")
    print(f"    Mean:   {avg:.2f}ms")
    print(f"    Median: {median:.2f}ms")
    print(f"    Stdev:  {stdev:.2f}ms")
    print(f"    Range:  {min_t:.2f}ms - {max_t:.2f}ms")


def main():
    print("=" * 60)
    print("Velo Startup Benchmark")
    print("=" * 60)
    print(f"Test script: {TEST_SCRIPT}")
    print(f"Iterations: {ITERATIONS}")
    print()

    # Ensure velo is built
    print("🔨 Building Velo (release)...", end="", flush=True)
    result = subprocess.run(["cargo", "build", "--release"], capture_output=True)
    if result.returncode != 0:
        print(" ❌ Build failed!")
        sys.exit(1)
    print(" ✅")
    print()

    # Warmup runs (to populate caches)
    print(f"🔥 Warmup ({WARMUP_RUNS} runs each)...")
    for _ in range(WARMUP_RUNS):
        subprocess.run([sys.executable, TEST_SCRIPT], capture_output=True)
        subprocess.run([VELO_BIN, "run", TEST_SCRIPT], capture_output=True)
    print()

    # Benchmark CPython
    print("📊 Benchmarking CPython...")
    cpython_times = measure_startup([sys.executable, TEST_SCRIPT])
    print_stats("CPython", cpython_times)
    print()

    # Benchmark Velo
    print("📊 Benchmarking Velo...")
    velo_times = measure_startup([VELO_BIN, "run", TEST_SCRIPT])
    print_stats("Velo", velo_times)
    print()

    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    if cpython_times and velo_times:
        cpython_avg = statistics.mean(cpython_times)
        velo_avg = statistics.mean(velo_times)
        ratio = velo_avg / cpython_avg
        print(f"  CPython avg:  {cpython_avg:.2f}ms")
        print(f"  Velo avg:     {velo_avg:.2f}ms")
        print(f"  Ratio:        {ratio:.1f}x slower")
        
        if ratio > 1:
            target = cpython_avg * 3  # Target: 3x slower max
            improvement_needed = ((velo_avg - target) / velo_avg) * 100
            print(f"\n  🎯 Target (3x): {target:.2f}ms")
            if velo_avg > target:
                print(f"  📉 Need {improvement_needed:.0f}% improvement")
            else:
                print(f"  ✅ Already meeting target!")


if __name__ == "__main__":
    main()
