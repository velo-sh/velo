"""
CPython Runner - Traditional Serverless Execution Model

Simulates traditional serverless: each request spawns a new Python process,
pays full interpreter startup and import costs.

For each request:
  1. subprocess.Popen(["python3", "handler.py"])
  2. Wait for completion
  3. Collect timing + RSS
"""
import subprocess
import sys
import time
import os
import resource
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple

HANDLER_PATH = Path(__file__).parent / "handler.py"


@dataclass
class RunResult:
    """Result of a single CPython run."""
    elapsed_ms: float
    rss_mb: float
    success: bool
    output: str


def get_rss_mb() -> float:
    """Get RSS in MB using resource module (cross-platform)."""
    # On macOS, ru_maxrss is in bytes; on Linux, it's in KB
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    else:
        return usage.ru_maxrss / 1024


def run_single(event: dict) -> RunResult:
    """
    Run handler in a fresh Python subprocess.
    
    This simulates traditional serverless cold start:
    - New Python interpreter
    - Fresh imports
    - Execute handler
    - Exit
    """
    start = time.perf_counter()
    
    try:
        result = subprocess.run(
            [sys.executable, str(HANDLER_PATH)],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "EVENT_DATA": json.dumps(event)},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        rss_mb = get_rss_mb()
        
        return RunResult(
            elapsed_ms=elapsed_ms,
            rss_mb=rss_mb,
            success=result.returncode == 0,
            output=result.stdout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            elapsed_ms=30000,
            rss_mb=0,
            success=False,
            output="Timeout",
        )
    except Exception as e:
        return RunResult(
            elapsed_ms=(time.perf_counter() - start) * 1000,
            rss_mb=0,
            success=False,
            output=str(e),
        )


def run_batch(n: int, event: dict = None) -> List[RunResult]:
    """Run N cold starts sequentially."""
    if event is None:
        event = {"test": "payload"}
    
    results = []
    for i in range(n):
        result = run_single(event)
        results.append(result)
    
    return results


if __name__ == "__main__":
    import statistics
    
    print("CPython Runner - Cold Start Benchmark")
    print("=" * 50)
    
    # Warm-up (discarded)
    print("Warm-up run (discarded)...")
    _ = run_single({"warmup": True})
    
    # Actual runs
    N = 5
    print(f"Running {N} cold starts...")
    results = run_batch(N)
    
    times = [r.elapsed_ms for r in results]
    print(f"\nResults:")
    print(f"  Median: {statistics.median(times):.2f}ms")
    print(f"  Mean:   {statistics.mean(times):.2f}ms")
    print(f"  Stdev:   {statistics.stdev(times):.2f}ms" if len(times) > 1 else "")
