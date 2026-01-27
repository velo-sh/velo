#!/usr/bin/env python3
"""
RFC-0035 Startup Time Benchmark

Measures Python startup time with and without native library preloading
to quantify the performance benefit.

Usage:
    python scripts/benchmark-startup.py [--iterations N] [--library IMPORT_NAME]
"""

import argparse
import statistics
import subprocess
import sys
from pathlib import Path


def measure_import_time(python_path: str, import_name: str, with_preload: bool = False) -> float:
    """
    Measure the time to import a library.
    Returns time in milliseconds.
    """
    env = {}
    if with_preload:
        # Enable Velo preloading
        env["VELO_PRELOAD_ENABLED"] = "1"

    code = f"""
import time
start = time.perf_counter()
import {import_name}
end = time.perf_counter()
print(f"{{(end - start) * 1000:.2f}}")
"""

    try:
        result = subprocess.run(
            [python_path, "-c", code], capture_output=True, text=True, timeout=30, env={**subprocess.os.environ, **env}
        )
        if result.returncode != 0:
            print(f"  Error: {result.stderr.strip()}", file=sys.stderr)
            return -1.0
        return float(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return -1.0
    except ValueError:
        return -1.0


def run_benchmark(python_path: str, import_name: str, iterations: int = 5, warmup: int = 1) -> dict:
    """Run benchmark and return statistics."""

    print(f"\n📊 Benchmarking: import {import_name}")
    print(f"   Python: {python_path}")
    print(f"   Iterations: {iterations} (+ {warmup} warmup)\n")

    # Warmup runs (not measured)
    print("🔥 Warming up...")
    for _ in range(warmup):
        measure_import_time(python_path, import_name)

    # Standard Python import (no preload)
    print("⏱️  Measuring standard import...")
    standard_times = []
    for i in range(iterations):
        t = measure_import_time(python_path, import_name, with_preload=False)
        if t > 0:
            standard_times.append(t)
            print(f"     Run {i + 1}: {t:.2f} ms")

    # With preload (if Velo is available)
    print("⏱️  Measuring with preload...")
    preload_times = []
    for i in range(iterations):
        t = measure_import_time(python_path, import_name, with_preload=True)
        if t > 0:
            preload_times.append(t)
            print(f"     Run {i + 1}: {t:.2f} ms")

    # Calculate statistics
    result = {
        "import": import_name,
        "iterations": iterations,
    }

    if standard_times:
        result["standard"] = {
            "mean": statistics.mean(standard_times),
            "median": statistics.median(standard_times),
            "stdev": statistics.stdev(standard_times) if len(standard_times) > 1 else 0,
            "min": min(standard_times),
            "max": max(standard_times),
        }

    if preload_times:
        result["preload"] = {
            "mean": statistics.mean(preload_times),
            "median": statistics.median(preload_times),
            "stdev": statistics.stdev(preload_times) if len(preload_times) > 1 else 0,
            "min": min(preload_times),
            "max": max(preload_times),
        }

    # Calculate speedup
    if standard_times and preload_times:
        speedup = statistics.mean(standard_times) / statistics.mean(preload_times)
        result["speedup"] = speedup

    return result


def print_results(results: dict):
    """Print benchmark results in a formatted table."""
    print("\n" + "=" * 60)
    print(f"📈 BENCHMARK RESULTS: import {results['import']}")
    print("=" * 60)

    if "standard" in results:
        s = results["standard"]
        print("\n🐍 Standard Python Import:")
        print(f"   Mean:   {s['mean']:.2f} ms")
        print(f"   Median: {s['median']:.2f} ms")
        print(f"   StdDev: {s['stdev']:.2f} ms")
        print(f"   Range:  {s['min']:.2f} - {s['max']:.2f} ms")

    if "preload" in results:
        p = results["preload"]
        print("\n⚡ With Velo Preload:")
        print(f"   Mean:   {p['mean']:.2f} ms")
        print(f"   Median: {p['median']:.2f} ms")
        print(f"   StdDev: {p['stdev']:.2f} ms")
        print(f"   Range:  {p['min']:.2f} - {p['max']:.2f} ms")

    if "speedup" in results:
        speedup = results["speedup"]
        if speedup > 1:
            print(f"\n✅ Speedup: {speedup:.2f}x faster with preload")
        elif speedup < 1:
            print(f"\n⚠️  Slowdown: {1 / speedup:.2f}x slower with preload")
        else:
            print("\n➖ No difference")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Benchmark Python startup time with native library preloading")
    parser.add_argument("--iterations", "-n", type=int, default=5, help="Number of measurement iterations (default: 5)")
    parser.add_argument(
        "--library", "-l", type=str, default="msgpack", help="Library to import for benchmark (default: msgpack)"
    )
    parser.add_argument(
        "--python", type=str, default=".venv/bin/python", help="Path to Python interpreter (default: .venv/bin/python)"
    )
    parser.add_argument("--warmup", "-w", type=int, default=1, help="Number of warmup iterations (default: 1)")

    args = parser.parse_args()

    # Verify Python exists
    python_path = Path(args.python)
    if not python_path.exists():
        print(f"❌ Python not found: {python_path}", file=sys.stderr)
        sys.exit(1)

    # Run benchmark
    results = run_benchmark(
        python_path=str(python_path), import_name=args.library, iterations=args.iterations, warmup=args.warmup
    )

    # Print results
    print_results(results)


if __name__ == "__main__":
    main()
