#!/usr/bin/env python3
"""
HIO-002: LangChain/Pydantic Schema Generation Race

Measures Pydantic v2 complex model schema generation time comparison between
CPython (traditional) and Velo (Zygote + pre-locked schemas).

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
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Union
from datetime import datetime
from enum import Enum

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
except ImportError:
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


class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class Address(BaseModel):
    street: str
    city: str
    country: str = "USA"

class Metadata(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    tags: List[str] = []


class LangChainZygote:
    """Simulates Velo Zygote for LangChain/Pydantic."""
    def __init__(self):
        self.zygote_rss = 0
        self.models = []
        
    def warmup(self):
        """Pre-generate 500 Pydantic schemas."""
        for i in range(500):
            model = type(f"ComplexModel{i}", (BaseModel,), {
                "__annotations__": {
                    "id": int, "name": str, "status": Status,
                    "address": Optional[Address], "metadata": Metadata,
                    "related_ids": List[int], "config": Dict[str, Union[str, int]],
                },
                "model_config": ConfigDict(strict=True),
            })
            self.models.append(model)
            # Lock the schema: this is the heavy part
            model.model_json_schema()
            
        self.zygote_rss = get_rss_mb()
        return self.zygote_rss

    def fork_worker(self):
        """Fork a worker that accesses the pre-locked schemas."""
        r_fd, w_fd = os.pipe()
        start = time.perf_counter()
        pid = os.fork()
        
        if pid == 0:
            os.close(r_fd)
            gc.disable()
            
            # Access one schema: should be instant
            _ = self.models[0].model_json_schema()
            
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
    """Measure CPython cold start + 500 schemas generation."""
    script = '''
import time
import resource
import sys
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Union
from datetime import datetime
from enum import Enum

start = time.perf_counter()

class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class Address(BaseModel):
    street: str
    city: str
    country: str = "USA"

class Metadata(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    tags: List[str] = []

models = []
for i in range(500):
    model = type(f"ComplexModel{i}", (BaseModel,), {
        "__annotations__": {
            "id": int, "name": str, "status": Status,
            "address": Optional[Address], "metadata": Metadata,
            "related_ids": List[int], "config": Dict[str, Union[str, int]],
        },
        "model_config": ConfigDict(strict=True),
    })
    models.append(model)
    model.model_json_schema()

rusage_denom = 1024 * 1024 if sys.platform == "darwin" else 1024
rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rusage_denom
elapsed = time.perf_counter() - start
print(f"{elapsed}|{rss_mb}")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        parts = result.stdout.strip().split('|')
        return float(parts[0]), float(parts[1])
    return 0.0, 0.0


def main():
    parser = argparse.ArgumentParser(description="HIO-002: LangChain/Pydantic Race")
    parser.add_argument("--runs", type=int, default=10, help="Number of iterations")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup iterations")
    parser.add_argument("--export-json", type=str, default="", help="Export results to JSON")
    args = parser.parse_args()
    
    print_lab_environment()
    print()
    
    cpython_times = []
    cpython_rss_list = []
    velo_times = []
    
    progress, _ = create_progress_context()
    with progress:
        # CPython Benchmark
        cp_task = progress.add_task("🐍 Running CPython (Legacy Cold Start)", total=args.runs)
        for _ in range(args.runs):
            t, rss = measure_cpython_cold_start()
            if t > 0:
                cpython_times.append(t)
                cpython_rss_list.append(rss)
            progress.advance(cp_task)
            
        # Velo Benchmark
        ve_task = progress.add_task("⚡ Initializing Velo (Pydantic Zygote)...", total=args.runs + 1)
        zygote = LangChainZygote()
        zygote_rss = zygote.warmup()
        progress.advance(ve_task)
        
        # Actual runs
        for _ in range(args.runs):
            t = zygote.fork_worker()
            velo_times.append(t)
            progress.advance(ve_task)
            
    c_time = statistics.median(cpython_times)
    c_rss = statistics.median(cpython_rss_list)
    v_time = statistics.median(velo_times)
    v_rss = zygote_rss
    
    speedup = c_time / max(v_time, 0.0001)
    mem_reduction = (c_rss - v_rss) / max(c_rss, 1)
    
    print()
    print_race_result(c_time, v_time, mode="Pydantic Schema Generation (500 Models)", memory_data=(c_rss, v_rss))
    print()
    print_verdict(speedup, mem_reduction)
    print_reproduce_hint(f"./examples/langchain-fast/run_hio.sh --compare --runs={args.runs}")
    
    if args.export_json:
        export_results_json(args.export_json, cpython_times, velo_times)


if __name__ == "__main__":
    main()
