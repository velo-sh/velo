"""
HIO-004 Benchmark - Serverless Cold Start Comparison

Orchestrates the comparison between CPython (traditional) and Velo (Zygote + fork)
execution models for serverless cold start scenarios.

Uses unified hio_visual standard for output.
"""

import sys
import time
import statistics
import argparse
from pathlib import Path
from typing import List
from dataclasses import dataclass

# Add parent to path for shared scripts
BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(BASE_DIR))

# Import unified visual components
try:
    from hio_visual import (
        print_lab_environment,
        print_race_result,
        print_verdict,
        print_reproduce_hint,
        create_progress_context,
        create_progress_context,
        export_results_json,
        save_summary_metric,
        IS_QUIET,
    )

    HAS_VISUAL = True
except ImportError:
    HAS_VISUAL = False

    def print_lab_environment():
        print("=== VELO PERFORMANCE LABS ===")

    def print_race_result(c, v, mode="", memory_data=None):
        print(f"CPython: {c:.3f}s | Velo: {v:.3f}s")

    def print_verdict(speedup, mem_red=0):
        print(f"SUMMARY: Velo is {speedup:.1f}x faster")

    def print_reproduce_hint(cmd):
        pass

    def create_progress_context():
        class D:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def add_task(self, *a, **k):
                return 0

            def advance(self, *a):
                pass

            def remove_task(self, *a):
                pass

        return D(), False

    def export_results_json(*a, **k):
        pass

    def save_summary_metric(*a, **k):
        pass

    IS_QUIET = False


@dataclass
class BenchmarkResult:
    cpython_times: List[float]
    velo_times: List[float]
    cpython_rss: float
    velo_rss: float
    zygote_warmup_ms: float


def run_benchmark(runs: int = 5, warmup: int = 1) -> BenchmarkResult:
    """
    Run A/B comparison benchmark with progress bars.
    """
    from cpython_runner import run_batch as cpython_batch, run_single as cpython_single
    from velo_runner import VeloZygote

    progress, _ = create_progress_context()

    cpython_times = []
    velo_times = []
    cpython_rss = 0
    velo_rss = 0
    zygote_warmup = 0

    with progress:
        # --- Warmup Phase ---
        if warmup > 0:
            if not IS_QUIET:
                warmup_task = progress.add_task("🔥 Warming up...", total=warmup)
            for _ in range(warmup):
                _ = cpython_single({"warmup": True})
                if not IS_QUIET:
                    progress.advance(warmup_task)
            if not IS_QUIET:
                progress.remove_task(warmup_task)

        # --- CPython Baseline ---
        cp_task = progress.add_task("🐍 Running CPython (Legacy Runtime)", total=runs)
        cpython_results = []
        for i in range(runs):
            result = cpython_single({"run": i})
            cpython_results.append(result)
            progress.advance(cp_task)

        cpython_times = [r.elapsed_ms / 1000 for r in cpython_results]  # Convert to seconds
        cpython_rss = max(r.rss_mb for r in cpython_results) if cpython_results else 66.0

        # --- Velo (Zygote + fork) ---
        zygote = VeloZygote()
        zygote_warmup = zygote.warmup()

        # Warmup fork
        _ = zygote.fork_and_handle({"warmup": True})

        ve_task = progress.add_task("⚡ Running Velo (Zygote Optimization)", total=runs)
        velo_results = []
        for i in range(runs):
            result = zygote.fork_and_handle({"run": i})
            velo_results.append(result)
            progress.advance(ve_task)

        velo_times = [r.elapsed_ms / 1000 for r in velo_results]  # Convert to seconds
        velo_rss = zygote.zygote_rss_mb

    return BenchmarkResult(
        cpython_times=cpython_times,
        velo_times=velo_times,
        cpython_rss=cpython_rss,
        velo_rss=velo_rss,
        zygote_warmup_ms=zygote_warmup,
    )


def main():
    parser = argparse.ArgumentParser(description="HIO-004 Serverless Benchmark")
    parser.add_argument("--runs", type=int, default=5, help="Number of iterations")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup iterations")
    parser.add_argument("--export-json", type=str, default="", help="Export results to JSON")
    args = parser.parse_args()
    if args.runs < 1 or args.warmup < 0:
        print("\n[ERROR] Invalid parameters: --runs must be >= 1 and --warmup must be >= 0.")
        sys.exit(1)

    # Print LAB ENVIRONMENT
    print_lab_environment()
    print()

    # Run benchmark
    result = run_benchmark(runs=args.runs, warmup=args.warmup)

    if not result.cpython_times or not result.velo_times:
        print("\n[ERROR] Benchmark produced no results. Check your environment.")
        sys.exit(1)

    # Calculate statistics
    cpython_median = statistics.median(result.cpython_times)
    velo_median = statistics.median(result.velo_times)
    speedup = cpython_median / max(velo_median, 0.0001)
    mem_reduction = (result.cpython_rss - result.velo_rss) / max(result.cpython_rss, 1)

    print()

    # Print comparison table
    print_race_result(
        cpython_median,
        velo_median,
        mode=f"Serverless Cold Start (Median of {args.runs} runs)",
        memory_data=(result.cpython_rss, result.velo_rss),
    )

    print()

    # Print verdict
    print_verdict(speedup, mem_reduction)

    # Reproduction hint
    print_reproduce_hint(f"./examples/serverless-instant/run_hio.sh --compare --runs={args.runs}")

    # Export JSON if requested
    if args.export_json:
        export_results_json(
            args.export_json,
            result.cpython_times,
            result.velo_times,
            cpython_label="CPython (Cold Start)",
            velo_label="Velo (Zygote Fork)",
        )

    # Save summary for demo
    save_summary_metric(
        "Serverless Computing (Cold Start)",
        f"{speedup:.1f}x faster cold start",
        mem_save=mem_reduction,
        cpython_time=cpython_median,
        velo_time=velo_median,
        cpython_rss=result.cpython_rss,
        velo_rss=result.velo_rss,
    )


if __name__ == "__main__":
    main()
