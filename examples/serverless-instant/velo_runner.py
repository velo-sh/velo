"""
Velo Runner - Zygote + Fork Execution Model

Simulates Velo's execution model:
  1. Zygote process: import handler once
  2. For each request: fork() → execute → exit
  3. Memory shared via Copy-On-Write

Key optimizations:
  - gc.disable() in child to prevent CoW trigger
  - Interpreter and imports paid once
  - Per-request cost dominated by fork()
"""

import gc
import os
import resource
import sys
import time
from dataclasses import dataclass

# macOS fork safety
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")


@dataclass
class RunResult:
    """Result of a single Velo fork run."""

    elapsed_ms: float
    rss_mb: float
    success: bool
    output: str


def get_rss_mb() -> float:
    """Get RSS in MB using resource module (cross-platform)."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    else:
        return usage.ru_maxrss / 1024


class VeloZygote:
    """
    Simulates Velo's Zygote process model.

    The Zygote pre-warms the Python runtime:
    - Interpreter is already running
    - Handler and dependencies are imported
    - Ready to fork() on each request
    """

    def __init__(self):
        self.zygote_start = time.perf_counter()
        self.handler_module = None
        self.zygote_rss_mb = 0
        self.warmup_time_ms = 0

    def warmup(self):
        """
        Pre-warm the Zygote by importing handler.
        This cost is paid once and amortized.
        """
        start = time.perf_counter()

        # Import handler (pays import cost once)
        from handler import LOADED_MODULES, handler

        self.handler_module = handler
        self.loaded_modules = LOADED_MODULES

        self.warmup_time_ms = (time.perf_counter() - start) * 1000
        self.zygote_rss_mb = get_rss_mb()

        return self.warmup_time_ms

    def fork_and_handle(self, event: dict) -> RunResult:
        """
        Fork a worker to handle a single request.

        The child process:
        1. Disables GC to prevent CoW trigger
        2. Executes handler
        3. Exits immediately

        The parent collects timing and waits for child.
        """
        # Pipe for child → parent communication
        read_fd, write_fd = os.pipe()

        start = time.perf_counter()
        pid = os.fork()

        if pid == 0:
            # Child process
            os.close(read_fd)

            # Disable GC to prevent CoW (P1 requirement)
            gc.disable()

            try:
                result = self.handler_module(event)
                output = str(result)
                success = True
            except Exception as e:
                output = str(e)
                success = False

            # Report back to parent
            elapsed_ms = (time.perf_counter() - start) * 1000
            rss_mb = get_rss_mb()

            import json

            msg = json.dumps(
                {
                    "elapsed_ms": elapsed_ms,
                    "rss_mb": rss_mb,
                    "success": success,
                    "output": output,
                }
            )
            os.write(write_fd, msg.encode())
            os.close(write_fd)

            # Exit child immediately
            os._exit(0)
        else:
            # Parent process
            os.close(write_fd)

            # Wait for child
            os.waitpid(pid, 0)

            # Read result from pipe
            import json

            data = os.read(read_fd, 4096).decode()
            os.close(read_fd)

            try:
                result = json.loads(data)
                return RunResult(
                    elapsed_ms=result["elapsed_ms"],
                    rss_mb=result["rss_mb"],
                    success=result["success"],
                    output=result["output"],
                )
            except json.JSONDecodeError:
                elapsed_ms = (time.perf_counter() - start) * 1000
                return RunResult(
                    elapsed_ms=elapsed_ms,
                    rss_mb=0,
                    success=False,
                    output="Failed to parse child result",
                )

    def run_batch(self, n: int, event: dict = None) -> list[RunResult]:
        """Run N forked requests."""
        if event is None:
            event = {"test": "payload"}

        results = []
        for _i in range(n):
            result = self.fork_and_handle(event)
            results.append(result)

        return results


if __name__ == "__main__":
    import statistics

    print("Velo Runner - Zygote + Fork Benchmark")
    print("=" * 50)

    # Create Zygote
    zygote = VeloZygote()
    warmup_ms = zygote.warmup()
    print(f"Zygote warmup: {warmup_ms:.2f}ms (one-time cost)")
    print(f"Zygote RSS: {zygote.zygote_rss_mb:.1f}MB")
    print(f"Loaded modules: {zygote.loaded_modules}")

    # Warm-up fork (discarded)
    print("\nWarm-up fork (discarded)...")
    _ = zygote.fork_and_handle({"warmup": True})

    # Actual runs
    N = 5
    print(f"Running {N} forked requests...")
    results = zygote.run_batch(N)

    times = [r.elapsed_ms for r in results]
    print("\nResults (fork only):")
    print(f"  Median: {statistics.median(times):.2f}ms")
    print(f"  Mean:   {statistics.mean(times):.2f}ms")
    print(f"  Stdev:  {statistics.stdev(times):.2f}ms" if len(times) > 1 else "")
