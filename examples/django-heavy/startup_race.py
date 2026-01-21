#!/usr/bin/env python3
"""
HIO-001: Django Heavyweight Startup Race

Measures Django App Registry initialization time comparison between
CPython (traditional) and Velo (Zygote + fork) execution models.

Uses unified hio_visual standard for output.
"""
import os
import sys
import time
import subprocess
import statistics
import argparse
import gc
import resource
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
        print(f"CPython: {c:.3f}s | Velo: {v:.3f}s")
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


def get_rss_mb() -> float:
    """Get RSS in MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    denom = 1024 * 1024 if sys.platform == "darwin" else 1024
    return usage.ru_maxrss / denom


class DjangoZygote:
    """Simulates Velo Zygote for Django."""
    def __init__(self):
        self.rss_before = get_rss_mb()
        self.zygote_rss = 0
        
    def warmup(self):
        """Pre-warm the Zygote by initializing Django."""
        # Setup Django environment
        skeleton_path = str(BASE_DIR / "skeleton")
        sys.path.insert(0, skeleton_path)
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "demo_project.settings")
        
        # Load heavy dependencies (simulated if missing)
        try:
            import numpy
            import pandas
        except ImportError:
            # Emulate 50MB of dependency memory
            self._mem_hold = bytearray(50 * 1024 * 1024)
            self._mem_hold[0] = 1
            self._mem_hold[-1] = 1
            
        import django
        from django.apps import apps
        django.setup()
        
        # Force app registry load
        apps.get_app_configs()
        
        self.zygote_rss = get_rss_mb()
        return self.zygote_rss

    def fork_worker(self):
        """Fork a worker that handles a 'request' from the pre-warmed state."""
        r_fd, w_fd = os.pipe()
        start = time.perf_counter()
        pid = os.fork()
        
        if pid == 0:
            os.close(r_fd)
            gc.disable() # Standard Velo optimization
            
            # Simple proof of initialization: access the registry
            from django.apps import apps
            try:
                _ = apps.get_app_config('heavy_app')
            except:
                pass
                
            elapsed = time.perf_counter() - start
            os.write(w_fd, str(elapsed).encode())
            os._exit(0)
        else:
            os.close(w_fd)
            os.waitpid(pid, 0)
            elapsed = float(os.read(r_fd, 64).decode())
            os.close(r_fd)
            return elapsed


def measure_cpython_cold_start() -> tuple:
    """Measure real CPython cold start + setup."""
    script = '''
import time
import os
import sys
import resource

skeleton_path = os.getcwd() + "/examples/django-heavy/skeleton"
sys.path.insert(0, skeleton_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "demo_project.settings")

start = time.perf_counter()

# Emulate heavy dependency loading
try:
    import numpy
    import pandas
except ImportError:
    heavy_dependency_simulation = bytearray(50 * 1024 * 1024)
    heavy_dependency_simulation[0] = 1 
    heavy_dependency_simulation[-1] = 1

# Real Django App Registry load
import django
django.setup()

from django.apps import apps
for app_config in apps.get_app_configs():
    for model in app_config.get_models():
        pass

rusage_denom = 1024 * 1024 if sys.platform == "darwin" else 1024
rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rusage_denom
elapsed = time.perf_counter() - start
print(f"{elapsed}|{rss_mb}")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=os.getcwd()
    )
    
    if result.returncode == 0 and result.stdout.strip():
        parts = result.stdout.strip().split('|')
        return float(parts[0]), float(parts[1])
    return 0.0, 0.0


def main():
    parser = argparse.ArgumentParser(description="HIO-001: Django Startup Race")
    parser.add_argument("--runs", type=int, default=10, help="Number of iterations")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup iterations")
    parser.add_argument("--export-json", type=str, default="", help="Export results to JSON")
    args = parser.parse_args()
    
    # Print LAB ENVIRONMENT
    print_lab_environment()
    print()
    
    cpython_times = []
    cpython_rss_list = []
    velo_times = []
    
    progress, _ = create_progress_context()
    with progress:
        # CPython Benchmark (Cold Starts)
        cp_task = progress.add_task("🐍 Running CPython (Legacy Cold Start)", total=args.runs)
        for _ in range(args.runs):
            t, rss = measure_cpython_cold_start()
            if t > 0:
                cpython_times.append(t)
                cpython_rss_list.append(rss)
            progress.advance(cp_task)
            
        # Velo Benchmark (Zygote + Fork)
        ve_task = progress.add_task("⚡ Initializing Velo (Django Zygote)...", total=args.runs + 1)
        zygote = DjangoZygote()
        zygote_rss = zygote.warmup()
        progress.advance(ve_task)
        
        # Warmup fork
        _ = zygote.fork_worker()
        
        # Actual runs
        for _ in range(args.runs):
            t = zygote.fork_worker()
            velo_times.append(t)
            progress.advance(ve_task)
            
    # Calculate statistics
    c_time = statistics.median(cpython_times)
    c_rss = statistics.median(cpython_rss_list)
    v_time = statistics.median(velo_times)
    v_rss = zygote_rss
    
    speedup = c_time / max(v_time, 0.0001)
    mem_reduction = (c_rss - v_rss) / max(c_rss, 1) # Note: CoW sharing makes this even better in multi-worker
    
    print()
    print_race_result(c_time, v_time, mode="Django App Registry Init", memory_data=(c_rss, v_rss))
    print()
    print_verdict(speedup, mem_reduction)
    print_reproduce_hint(f"./examples/django-heavy/run_hio.sh --compare --runs={args.runs}")
    
    if args.export_json:
        export_results_json(args.export_json, cpython_times, velo_times)


if __name__ == "__main__":
    main()
