"""
HIO-004 Benchmark - A/B Comparison Engine

Orchestrates the comparison between CPython (traditional) and Velo (Zygote + fork)
execution models for serverless cold start scenarios.

Scenarios:
  - single: Single cold start comparison
  - burst:  N=10 concurrent cold starts
  - memory: RSS memory comparison

Statistical rigor:
  - Warm-up run discarded
  - Outputs median and p95
  - Python version displayed for fairness
"""
import sys
import time
import statistics
import argparse
from typing import Tuple, List
from dataclasses import dataclass

# Add parent to path for shared scripts
sys.path.insert(0, str(__file__).rsplit("/examples/", 1)[0])

try:
    from examples.scripts.hio_visual import print_header, print_race_result, print_score
    HAS_VISUAL = True
except ImportError:
    HAS_VISUAL = False


@dataclass
class BenchmarkResult:
    cpython_times: List[float]
    velo_times: List[float]
    cpython_rss: float
    velo_rss: float
    zygote_warmup_ms: float


def run_benchmark(scenario: str = "single", runs: int = 5) -> BenchmarkResult:
    """
    Run A/B comparison benchmark.
    
    Args:
        scenario: 'single', 'burst', or 'memory'
        runs: Number of iterations
    
    Returns:
        BenchmarkResult with timing and memory data
    """
    from cpython_runner import run_batch as cpython_batch, run_single as cpython_single
    from velo_runner import VeloZygote
    
    print(f"\n{'='*60}")
    print(f" HIO-004 SERVERLESS BENCHMARK")
    print(f" Scenario: {scenario} | Runs: {runs}")
    print(f" Python: {sys.version.split()[0]}")
    print(f"{'='*60}\n")
    
    # --- CPython Baseline ---
    print("[CPython] Warm-up run (discarded)...")
    _ = cpython_single({"warmup": True})
    
    print(f"[CPython] Running {runs} cold starts...")
    cpython_results = cpython_batch(runs)
    cpython_times = [r.elapsed_ms for r in cpython_results]
    cpython_rss = max(r.rss_mb for r in cpython_results) if cpython_results else 0
    
    # --- Velo (Zygote + fork) ---
    print("\n[Velo] Initializing Zygote...")
    zygote = VeloZygote()
    zygote_warmup = zygote.warmup()
    print(f"[Velo] Zygote warmup: {zygote_warmup:.2f}ms (one-time)")
    
    print("[Velo] Warm-up fork (discarded)...")
    _ = zygote.fork_and_handle({"warmup": True})
    
    print(f"[Velo] Running {runs} forked requests...")
    velo_results = zygote.run_batch(runs)
    velo_times = [r.elapsed_ms for r in velo_results]
    velo_rss = zygote.zygote_rss_mb
    
    return BenchmarkResult(
        cpython_times=cpython_times,
        velo_times=velo_times,
        cpython_rss=cpython_rss,
        velo_rss=velo_rss,
        zygote_warmup_ms=zygote_warmup,
    )


def print_results(result: BenchmarkResult, scenario: str):
    """Print benchmark results with visual formatting."""
    cpython_median = statistics.median(result.cpython_times)
    velo_median = statistics.median(result.velo_times)
    
    # Calculate p95
    cpython_p95 = sorted(result.cpython_times)[int(len(result.cpython_times) * 0.95)] if len(result.cpython_times) >= 5 else max(result.cpython_times)
    velo_p95 = sorted(result.velo_times)[int(len(result.velo_times) * 0.95)] if len(result.velo_times) >= 5 else max(result.velo_times)
    
    speedup = cpython_median / max(velo_median, 0.01)
    
    print(f"\n{'='*60}")
    print(f" RESULTS (Scenario: {scenario})")
    print(f"{'='*60}")
    print(f"\n{'Metric':<20} {'CPython':<15} {'Velo':<15} {'Speedup':<10}")
    print(f"{'-'*60}")
    print(f"{'Median (ms)':<20} {cpython_median:<15.2f} {velo_median:<15.2f} {speedup:.1f}x ⚡")
    print(f"{'P95 (ms)':<20} {cpython_p95:<15.2f} {velo_p95:<15.2f}")
    
    if scenario == "memory":
        mem_saving = (result.cpython_rss - result.velo_rss) / max(result.cpython_rss, 0.01) * 100
        print(f"{'RSS (MB)':<20} {result.cpython_rss:<15.1f} {result.velo_rss:<15.1f} {mem_saving:.0f}% saved 📉")
    
    print(f"\n[Note] Zygote warmup: {result.zygote_warmup_ms:.2f}ms (amortized over all requests)")
    
    # Use shared visual if available (Progress Bar only)
    if HAS_VISUAL:
        memory_data = (result.cpython_rss, result.velo_rss) if scenario == "memory" else None
        print_race_result(
            cpython_median / 1000,  # Convert to seconds
            velo_median / 1000,
            mode=f"Cold Start ({scenario})",
            memory_data=memory_data,
        )
    
    return speedup


def main():
    parser = argparse.ArgumentParser(description="HIO-004 Serverless Benchmark")
    parser.add_argument("--scenario", choices=["single", "burst", "memory"], default="single")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    
    # Adjust runs for burst scenario
    runs = args.runs
    if args.scenario == "burst":
        runs = 10
    
    # Print header
    if HAS_VISUAL:
        print_header("HIO-004 (Serverless Instant)", "Cold Start → Near Zero")
    
    result = run_benchmark(scenario=args.scenario, runs=runs)
    speedup = print_results(result, args.scenario)
    
    # Calculate HIO Score
    if HAS_VISUAL:
        mem_reduction = (result.cpython_rss - result.velo_rss) / max(result.cpython_rss, 0.01)
        print_score(min(99, 70 + speedup / 2), mem_reduction)
    
    print(f"\n{'='*60}")
    print(f" ✅ Benchmark complete. Velo achieves {speedup:.1f}x speedup.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
