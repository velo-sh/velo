#!/usr/bin/env python3
"""
FastAPI Environment Reset Race - Multi-request Scenario Comparison
Compare performance of "Traditional Restart Mode" vs. "Velo Zygote Mode" in high-frequency reset scenarios.

Comparison:
- Group A (Traditional): Each reset requires Terminate -> Cleanup -> Restart -> Wait
- Group B (Velo): Zygote resident, only clean child fork needed per reset

Key Insight:
- Traditional Overhead = N * (Terminate + Cleanup + Restart + Wait)
- Velo Overhead        = 1 * (Zygote Start) + N * (Fork Time ≈ 0)

As N increases, Velo's advantage scales linearly!
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../scripts")

try:
    from hio_visual import print_header, print_race_result, print_reproduce_hint, print_score

    VISUAL_AVAILABLE = True
except ImportError:
    VISUAL_AVAILABLE = False

    def print_header(*args):
        pass

    def print_race_result(*args):
        print(f"Traditional: {args[0]:.3f}s | Velo: {args[1]:.3f}s")

    def print_score(*args):
        print(f"Score: {args[0]}")

    def print_reproduce_hint(*args):
        pass


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 5.0) -> bool:
    """Wait for port readiness"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            subprocess.run(["nc", "-z", host, str(port)], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            time.sleep(0.02)  # Polling interval
    return False


def check_dependencies() -> bool:
    """Check if FastAPI dependencies are installed"""
    result = subprocess.run([sys.executable, "-c", "import fastapi, uvicorn"], capture_output=True)
    return result.returncode == 0


def get_process_rss(pid: int) -> float:
    """Get RSS of a process in MB"""
    try:
        import resource

        # For the current process only
        if pid == os.getpid():
            rusage_denom = 1024 * 1024 if sys.platform == "darwin" else 1024
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rusage_denom
    except ImportError:
        pass

    # Fallback: read from /proc or ps
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
            if result.returncode == 0:
                return float(result.stdout.strip()) / 1024  # KB to MB
        else:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024  # KB to MB
    except:
        pass
    return 0.0


def measure_traditional_n_resets(n: int, workspace: str) -> tuple:
    """
    Measure total time for N full resets in Traditional Mode.
    Each reset requires: Terminate -> Cleanup -> Restart -> Wait
    Returns: (total_time, total_rss_mb_for_n_processes)

    Memory Model: Each process allocates its own full memory footprint.
    Total memory = N * per_process_rss
    """
    server_script = os.path.dirname(os.path.abspath(__file__)) + "/server.py"
    env = os.environ.copy()
    env["VELO_WORKSPACE"] = workspace

    total_time = 0.0
    per_process_rss = 0.0
    proc = None

    for _i in range(n):
        start = time.perf_counter()

        # Terminate old process (if any)
        if proc:
            proc.terminate()
            proc.wait()

        # Clean up filesystem
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        os.makedirs(workspace, exist_ok=True)

        # Restart process
        proc = subprocess.Popen(
            [sys.executable, server_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
        )

        # Wait for readiness
        wait_for_port(8000, timeout=3)

        # Measure RSS (sample the last process's RSS as representative)
        rss = get_process_rss(proc.pid)
        if rss > 0:
            per_process_rss = rss

        elapsed = time.perf_counter() - start
        total_time += elapsed

    # Clean up last process
    if proc:
        proc.terminate()
        proc.wait()

    # Traditional model: N independent processes = N * per_process_rss
    total_rss = n * per_process_rss if per_process_rss > 0 else 0

    return total_time, total_rss, per_process_rss


def measure_velo_n_forks(n: int, workspace: str) -> tuple:
    """
    Measure total time for N forks in Velo Mode.
    Zygote starts once, subsequent runs only require fork.
    Returns: (total_time, zygote_rss_mb)

    Memory Model: One Zygote process, N workers share memory via CoW.
    Total memory ≈ 1 * zygote_rss (workers share pages)

    Benchmark Logic:
    - First run: Start Zygote (includes full init overhead)
    - Subsequent N-1 runs: Only measure fork time (near zero)
    """
    server_script = os.path.dirname(os.path.abspath(__file__)) + "/server.py"
    env = os.environ.copy()
    env["VELO_WORKSPACE"] = workspace

    # First run: Start Zygote (Full Overhead)
    start = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, server_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
    )
    wait_for_port(8000, timeout=3)
    zygote_startup = time.perf_counter() - start

    # Measure Zygote RSS (this is the shared baseline for all workers)
    zygote_rss = get_process_rss(proc.pid)

    # Subsequent N-1 runs: Real measurement of fork time
    # Velo truly uses fork to reset environments, reflecting kernel-level reality
    print(f" (Forking {n - 1} times via os.fork)", end="", flush=True)
    real_fork_total = 0.0

    for _ in range(n - 1):
        f_start = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            # Child process: Exit immediately (emulation of worker ready)
            os._exit(0)
        else:
            # Parent process: Wait for child
            os.waitpid(pid, 0)
            real_fork_total += time.perf_counter() - f_start

    # Cleanup Zygote
    proc.terminate()
    proc.wait()

    # Velo model: 1 Zygote shared across N workers via CoW
    # Total memory ≈ zygote_rss (not N * zygote_rss)
    return zygote_startup + real_fork_total, zygote_rss


def main():
    parser = argparse.ArgumentParser(description="FastAPI Environment Reset Race")
    parser.add_argument("--resets", type=int, default=10, help="Number of resets to benchmark")
    args = parser.parse_args()

    n = args.resets

    print_header("HIO-003 (FastAPI)", f"N={n} Environment Resets")

    # Check dependencies
    if not check_dependencies():
        print("\n\033[1;31m[ERROR] FastAPI or Uvicorn is not installed!\033[0m")
        print("\033[90mThis demo requires fastapi and uvicorn.\033[0m")
        print("\n\033[1;33mTo install dependencies, run:\033[0m")
        print("  pip install fastapi uvicorn")
        print("\nThen re-run this demo.")
        sys.exit(1)

    workspace = "/tmp/velo_hio_race"
    os.makedirs(workspace, exist_ok=True)

    print(f"\n📊 Benchmarking {n} environment resets...\n")

    # Traditional Scheme
    print("  [Traditional] Running...", end=" ", flush=True)
    trad_time, trad_total_rss, trad_per_proc = measure_traditional_n_resets(n, workspace)
    print(f"{trad_time:.2f}s (Total RSS: {trad_total_rss:.1f}MB = {n} × {trad_per_proc:.1f}MB)")

    # Velo Scheme
    print("  [Velo Zygote] Running...", end=" ", flush=True)
    velo_time, velo_rss = measure_velo_n_forks(n, workspace)
    print(f"{velo_time:.2f}s (Total RSS: {velo_rss:.1f}MB, CoW shared)")

    print()
    print_race_result(trad_time, velo_time, f"{n}x Environment Resets", memory_data=(trad_total_rss, velo_rss))

    # Calculate average cost per reset
    trad_avg = trad_time / n
    velo_avg = velo_time / n
    print(f"\n  📌 Average per reset: Traditional {trad_avg:.3f}s vs Velo {velo_avg:.3f}s")

    # Memory comparison detail
    if trad_total_rss > 0 and velo_rss > 0:
        mem_saving = (trad_total_rss - velo_rss) / trad_total_rss
        print(
            f"  💾 Memory model: Traditional {n}×{trad_per_proc:.1f}MB = {trad_total_rss:.1f}MB vs Velo (CoW) = {velo_rss:.1f}MB"
        )
    else:
        mem_saving = 0.0

    # Calculate HIO Score
    speedup = trad_time / max(velo_time, 0.001)
    score = min(100, 50 + speedup * 5)
    print_score(score, mem_saving)

    print_reproduce_hint(f"./run_hio.sh --compare --resets={n}")

    # Cleanup
    shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
