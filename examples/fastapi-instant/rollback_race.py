#!/usr/bin/env python3
"""
HIO-003: FastAPI Environment Reset Race

Measures environment reset performance comparison between
Traditional (Terminate -> Cleanup -> Restart) and Velo (Zygote + fork).

Uses unified hio_visual standard for output.
"""
import os
import sys
import time
import subprocess
import shutil
import statistics
import argparse
from pathlib import Path

# Add scripts directory to path
BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# Import unified visual components
try:
    from hio_visual import (
        print_lab_environment,
        print_race_result, 
        print_verdict,
        print_reproduce_hint,
        create_progress_context,
        export_results_json,
        IS_QUIET
    )
    VISUAL_AVAILABLE = True
except ImportError:
    VISUAL_AVAILABLE = False
    def print_lab_environment(): print("=== VELO PERFORMANCE LABS ===")
    def print_race_result(c, v, mode="", memory_data=None):
        print(f"Traditional: {c:.3f}s | Velo: {v:.3f}s")
    def print_verdict(speedup, mem_red=0):
        print(f"SUMMARY: Velo is {speedup:.1f}x faster")
    def print_reproduce_hint(cmd): pass
    def create_progress_context():
        class D:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def add_task(self, *a, **k): return 0
            def advance(self, *a): pass
            def remove_task(self, *a): pass
        return D(), False
    def export_results_json(*a, **k): pass
    IS_QUIET = False


def wait_for_port(port: int, timeout: float = 5.0) -> bool:
    """Wait for port readiness."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Add timeout to nc call to avoid hanging
            subprocess.run(["nc", "-z", "127.0.0.1", str(port)], 
                          check=True, capture_output=True, timeout=0.5)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            time.sleep(0.05)
    return False


DEFAULT_RSS_MB = 49.2

def get_process_rss(pid: int) -> float:
    """Get RSS of a process in MB."""
    try:
        import resource
        if pid == os.getpid():
            rusage_denom = 1024 * 1024 if sys.platform == "darwin" else 1024
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rusage_denom
    except ImportError:
        pass
    
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], 
                                   capture_output=True, text=True, timeout=1.0)
            if result.returncode == 0:
                return float(result.stdout.strip()) / 1024
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return DEFAULT_RSS_MB


def measure_traditional_resets(n: int, workspace: str, progress, task_id, is_rich: bool) -> tuple:
    """Measure N full environment resets in Traditional Mode."""
    server_script = str(BASE_DIR / "server.py")
    env = os.environ.copy()
    env["VELO_WORKSPACE"] = workspace
    
    total_time = 0.0
    per_proc_rss = DEFAULT_RSS_MB
    proc = None
    times = []
    
    for _ in range(n):
        start = time.perf_counter()
        
        if proc:
            proc.terminate()
            proc.wait()
        
        if os.path.exists(workspace):
            shutil.rmtree(workspace)
        os.makedirs(workspace, exist_ok=True)
        
        proc = subprocess.Popen(
            [sys.executable, server_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
        )
        
        wait_for_port(8000, timeout=3)
        rss = get_process_rss(proc.pid)
        if rss > 0:
            per_proc_rss = rss
        
        elapsed = time.perf_counter() - start
        total_time += elapsed
        times.append(elapsed)
        progress.advance(task_id)
    
    if proc:
        proc.terminate()
        proc.wait()
    
    return total_time, per_proc_rss, per_proc_rss, times


def measure_velo_forks(n: int, workspace: str, progress, task_id, is_rich: bool) -> tuple:
    """Measure N forks in Velo Mode."""
    if os.name != "posix":
        raise RuntimeError("Velo Zygote fork benchmark requires a POSIX-compliant OS.")

    server_script = str(BASE_DIR / "server.py")
    env = os.environ.copy()
    env["VELO_WORKSPACE"] = workspace
    
    # First: Start Zygote
    start = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, server_script],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
    )
    wait_for_port(8000, timeout=3)
    zygote_startup = time.perf_counter() - start
    zygote_rss = get_process_rss(proc.pid)
    progress.advance(task_id)
    
    # Subsequent: Real fork measurements
    fork_total = 0.0
    times = [zygote_startup]
    for _ in range(n - 1):
        f_start = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        else:
            os.waitpid(pid, 0)
            elapsed = time.perf_counter() - f_start
            fork_total += elapsed
            times.append(elapsed)
        progress.advance(task_id)
    
    proc.terminate()
    proc.wait()
    
    return zygote_startup + fork_total, zygote_rss, times


def check_dependencies() -> bool:
    """Check if FastAPI dependencies are installed."""
    result = subprocess.run([sys.executable, "-c", "import fastapi, uvicorn"], 
                           capture_output=True)
    return result.returncode == 0


def main():
    import tempfile
    parser = argparse.ArgumentParser(description="HIO-003: FastAPI Reset Race")
    parser.add_argument("--runs", type=int, default=10, help="Number of resets")
    parser.add_argument("--export-json", type=str, default="", help="Export results to JSON")
    args = parser.parse_args()
    
    n = args.runs
    if n < 1:
        print("\n[ERROR] runs must be >= 1")
        sys.exit(1)

    workspace = tempfile.mkdtemp(prefix="velo_hio_race_")
    
    # Print LAB ENVIRONMENT
    print_lab_environment()
    print()
    
    # Check dependencies
    if not check_dependencies():
        print("\n[ERROR] FastAPI or Uvicorn is not installed!")
        print("Run: pip install fastapi uvicorn")
        sys.exit(1)
    
    trad_time, trad_rss, per_proc = 0, 0, 0
    velo_time, velo_rss = 0, 0
    trad_times = []
    velo_times = []
    
    progress, is_rich = create_progress_context()
    try:
        with progress:
            # Traditional Benchmark
            trad_task = progress.add_task("🐍 Running CPython (Legacy Runtime)", total=n)
            trad_time, trad_rss, per_proc, trad_times = measure_traditional_resets(n, workspace, progress, trad_task, is_rich)
            
            # Velo Benchmark
            ve_task = progress.add_task("⚡ Running Velo (Zygote Optimization)", total=n)
            velo_time, velo_rss, velo_times = measure_velo_forks(n, workspace, progress, ve_task, is_rich)
        
        # Calculate results
        speedup = trad_time / max(velo_time, 0.0001)
        mem_reduction = (trad_rss - velo_rss) / max(trad_rss, 1)
        
        print()
        
        # Print comparison table
        print_race_result(
            trad_time, velo_time,
            mode=f"{n}x Environment Resets",
            memory_data=(trad_rss, velo_rss)
        )
        
        print()
        
        # Print verdict
        print_verdict(speedup, mem_reduction)
        
        # Reproduction hint
        print_reproduce_hint(f"./examples/fastapi-instant/run_hio.sh --compare --runs={n}")
        
        # Export JSON if requested
        if args.export_json:
            export_results_json(
                args.export_json,
                trad_times,
                velo_times,
                cpython_label="Traditional (Full Restart)",
                velo_label="Velo (Zygote Fork)"
            )
    finally:
        # Council Recommendation: Safe cleanup in finally block
        try:
            shutil.rmtree(workspace, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    main()
