#!/usr/bin/env python3
"""
Velo Benchmark: Multi-mode startup time comparison.

Modes:
1. Warm      - Standard benchmark after warmup (default)
2. Cold      - Single run with OS cache purge (requires sudo)
3. Init-only - Measure just initialization time (no script execution)
4. Serverless - Simulate cold starts (purge cache between runs)
"""

import subprocess
import sys
import time
import statistics
import argparse
from pathlib import Path

VELO_BIN = "./target/release/velo"
TEST_SCRIPT = "tests/corpus/hello.py"
INIT_SCRIPT = "tests/corpus/init_only.py"  # Minimal script for init-only mode
VELO_CACHE = ".velo_cache"


def clear_velo_cache():
    """Remove Velo cache to simulate first run."""
    import shutil
    cache_path = Path(VELO_CACHE)
    if cache_path.exists():
        shutil.rmtree(cache_path)


def measure_startup(cmd: list[str], iterations: int = 10) -> list[float]:
    """Measure startup time in milliseconds."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True)
        elapsed = (time.perf_counter() - start) * 1000
        if result.returncode == 0:
            times.append(elapsed)
    return times


def measure_cold_start(cmd: list[str], clear_cache: bool = True) -> float | None:
    """Measure single cold start (cache cleared)."""
    if clear_cache:
        clear_velo_cache()
    
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True)
    elapsed = (time.perf_counter() - start) * 1000
    
    return elapsed if result.returncode == 0 else None


def measure_serverless(cmd: list[str], iterations: int = 5, is_velo: bool = False) -> list[float]:
    """Simulate serverless cold starts (clear cache between runs for Velo)."""
    # Warmup run to let OS cache the binary
    subprocess.run(cmd, capture_output=True)
    if is_velo:
        clear_velo_cache()
    
    times = []
    for i in range(iterations):
        print(f"    Run {i+1}/{iterations}...", end="", flush=True)
        if is_velo:
            clear_velo_cache()
        start = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True)
        elapsed = (time.perf_counter() - start) * 1000
        if result.returncode == 0:
            times.append(elapsed)
            print(f" {elapsed:.2f}ms")
        else:
            print(" failed")
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
    if len(times) > 1:
        print(f"    Stdev:  {stdev:.2f}ms")
        print(f"    Range:  {min_t:.2f}ms - {max_t:.2f}ms")


def ensure_init_script():
    """Create minimal init-only test script."""
    init_path = Path(INIT_SCRIPT)
    if not init_path.exists():
        init_path.write_text("pass\n")


def build_velo():
    """Build Velo in release mode."""
    print("🔨 Building Velo (release)...", end="", flush=True)
    result = subprocess.run(["cargo", "build", "--release"], capture_output=True)
    if result.returncode != 0:
        print(" ❌ Build failed!")
        sys.exit(1)
    print(" ✅")


def mode_warm(iterations: int):
    """Standard warm benchmark."""
    print("\n🔥 Warmup (2 runs each)...")
    for _ in range(2):
        subprocess.run([sys.executable, TEST_SCRIPT], capture_output=True)
        subprocess.run([VELO_BIN, "run", TEST_SCRIPT], capture_output=True)

    print(f"\n📊 Benchmarking CPython (warm, {iterations} runs)...")
    cpython_times = measure_startup([sys.executable, TEST_SCRIPT], iterations)
    print_stats("CPython", cpython_times)

    print(f"\n📊 Benchmarking Velo (warm, {iterations} runs)...")
    velo_times = measure_startup([VELO_BIN, "run", TEST_SCRIPT], iterations)
    print_stats("Velo", velo_times)

    return cpython_times, velo_times


def mode_cold():
    """Single cold start benchmark (Velo cache cleared)."""
    print("\n❄️  Cold Start Benchmark (Velo cache cleared)")
    
    print("\n📊 CPython (baseline)...")
    cpython_time = measure_cold_start([sys.executable, TEST_SCRIPT], clear_cache=False)
    if cpython_time:
        print(f"  CPython: {cpython_time:.2f}ms")
    
    print("\n📊 Velo (cache miss)...")
    velo_time = measure_cold_start([VELO_BIN, "run", TEST_SCRIPT], clear_cache=True)
    if velo_time:
        print(f"  Velo: {velo_time:.2f}ms")
    
    return [cpython_time] if cpython_time else [], [velo_time] if velo_time else []


def mode_init_only(iterations: int):
    """Init-only benchmark (minimal script)."""
    ensure_init_script()
    
    print(f"\n⚡ Init-Only Benchmark (script: 'pass', {iterations} runs)")
    
    # Warmup
    for _ in range(2):
        subprocess.run([sys.executable, INIT_SCRIPT], capture_output=True)
        subprocess.run([VELO_BIN, "run", INIT_SCRIPT], capture_output=True)

    print("\n📊 CPython init-only...")
    cpython_times = measure_startup([sys.executable, INIT_SCRIPT], iterations)
    print_stats("CPython", cpython_times)

    print("\n📊 Velo init-only...")
    velo_times = measure_startup([VELO_BIN, "run", INIT_SCRIPT], iterations)
    print_stats("Velo", velo_times)

    return cpython_times, velo_times


def mode_serverless(iterations: int):
    """Serverless simulation (Velo cache cleared between runs)."""
    print(f"\n☁️  Serverless Simulation ({iterations} runs each)")
    
    print("\n📊 CPython serverless...")
    cpython_times = measure_serverless([sys.executable, TEST_SCRIPT], iterations, is_velo=False)
    print_stats("CPython", cpython_times)

    print("\n📊 Velo serverless (cache miss each run)...")
    velo_times = measure_serverless([VELO_BIN, "run", TEST_SCRIPT], iterations, is_velo=True)
    print_stats("Velo", velo_times)

    return cpython_times, velo_times


def print_summary(cpython_times: list[float], velo_times: list[float]):
    """Print comparison summary."""
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    if cpython_times and velo_times:
        cpython_avg = statistics.mean(cpython_times)
        velo_avg = statistics.mean(velo_times)
        
        print(f"  CPython avg:  {cpython_avg:.2f}ms")
        print(f"  Velo avg:     {velo_avg:.2f}ms")
        
        if velo_avg < cpython_avg:
            speedup = (cpython_avg - velo_avg) / cpython_avg * 100
            print(f"  Result:       ✅ Velo is {speedup:.0f}% FASTER")
        else:
            ratio = velo_avg / cpython_avg
            print(f"  Ratio:        {ratio:.1f}x slower")


def main():
    parser = argparse.ArgumentParser(description="Velo Benchmark")
    parser.add_argument("--mode", "-m", 
                       choices=["warm", "cold", "init", "serverless", "all"],
                       default="warm",
                       help="Benchmark mode")
    parser.add_argument("--iterations", "-n", type=int, default=10,
                       help="Number of iterations (default: 10)")
    args = parser.parse_args()

    print("=" * 60)
    print("Velo Startup Benchmark")
    print("=" * 60)
    print(f"Mode: {args.mode}")
    
    build_velo()

    if args.mode == "warm":
        cpython, velo = mode_warm(args.iterations)
        print_summary(cpython, velo)
    
    elif args.mode == "cold":
        cpython, velo = mode_cold()
        print_summary(cpython, velo)
    
    elif args.mode == "init":
        cpython, velo = mode_init_only(args.iterations)
        print_summary(cpython, velo)
    
    elif args.mode == "serverless":
        cpython, velo = mode_serverless(args.iterations)
        print_summary(cpython, velo)
    
    elif args.mode == "all":
        print("\n" + "=" * 60)
        print("MODE 1: Warm Benchmark")
        print("=" * 60)
        mode_warm(args.iterations)
        
        print("\n" + "=" * 60)
        print("MODE 2: Init-Only Benchmark")
        print("=" * 60)
        mode_init_only(args.iterations)
        
        print("\n" + "=" * 60)
        print("MODE 3: Cold Start")
        print("=" * 60)
        mode_cold()
        
        print("\n" + "=" * 60)
        print("MODE 4: Serverless Simulation")
        print("=" * 60)
        mode_serverless(3)


if __name__ == "__main__":
    main()
