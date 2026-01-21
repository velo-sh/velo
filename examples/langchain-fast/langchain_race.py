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


def measure_import_speed(use_velo: bool = False) -> tuple:
    """Measure Pydantic complex model schema generation time."""
    if use_velo:
        # Velo Mode: Full 500 models schema generation (same workload as CPython)
        script = '''
import time
import resource
import sys
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Union
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
    else:
        # CPython: Full 500 models schema generation
        script = '''
import time
import resource
import sys
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Union
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
    
    env = os.environ.copy()
    if use_velo:
        env["VELO_ZYGOTE"] = "1"
    
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env
    )
    
    if result.returncode == 0 and result.stdout.strip():
        try:
            parts = result.stdout.strip().split('|')
            elapsed = float(parts[0])
            rss = float(parts[1]) if len(parts) > 1 else 0.0
            return elapsed, rss
        except (ValueError, IndexError):
            pass
    return 0.0, 0.0


def main():
    parser = argparse.ArgumentParser(description="HIO-002: LangChain/Pydantic Race")
    parser.add_argument("--runs", type=int, default=3, help="Number of iterations")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup iterations")
    parser.add_argument("--export-json", type=str, default="", help="Export results to JSON")
    args = parser.parse_args()
    if args.runs < 1 or args.warmup < 0:
        print("\n[ERROR] Invalid parameters: --runs must be >= 1 and --warmup must be >= 0.")
        sys.exit(1)
    
    # Print LAB ENVIRONMENT
    print_lab_environment()
    print()
    
    cpython_times = []
    cpython_rss_list = []
    velo_times = []
    velo_rss_list = []
    
    progress, _ = create_progress_context()
    with progress:
        # Warmup Phase
        if args.warmup > 0:
            warmup_task = progress.add_task("🔥 Warming up...", total=args.warmup * 2)
            for _ in range(args.warmup):
                measure_import_speed(use_velo=False)
                progress.advance(warmup_task)
                measure_import_speed(use_velo=True)
                progress.advance(warmup_task)
            progress.remove_task(warmup_task)
        
        # CPython Benchmark
        cp_task = progress.add_task("🐍 Running CPython (Legacy Runtime)", total=args.runs)
        for _ in range(args.runs):
            t, rss = measure_import_speed(use_velo=False)
            if t > 0:
                cpython_times.append(t)
                cpython_rss_list.append(rss)
            progress.advance(cp_task)
        
        # Velo Benchmark
        ve_task = progress.add_task("⚡ Running Velo (Zygote Optimization)", total=args.runs)
        for _ in range(args.runs):
            t, rss = measure_import_speed(use_velo=True)
            if t > 0:
                velo_times.append(t)
                velo_rss_list.append(rss)
            progress.advance(ve_task)
    
    # Handle errors
    if not cpython_times or not velo_times:
        print("\n[ERROR] Pydantic is not installed or benchmark failed!")
        print("Run: pip install 'pydantic>=2.0'")
        sys.exit(1)
    
    # Calculate statistics
    c_time = statistics.median(cpython_times)
    c_rss = statistics.median(cpython_rss_list)
    v_time = statistics.median(velo_times)
    v_rss = statistics.median(velo_rss_list)
    
    speedup = c_time / max(v_time, 0.001)
    mem_reduction = (c_rss - v_rss) / max(c_rss, 1)
    
    print()
    
    # Print comparison table
    print_race_result(c_time, v_time, mode="Pydantic Schema Generation (500 Models)", memory_data=(c_rss, v_rss))
    
    print()
    
    # Print verdict
    print_verdict(speedup, mem_reduction)
    
    # Reproduction hint
    print_reproduce_hint(f"./examples/langchain-fast/run_hio.sh --compare --runs={args.runs}")
    
    # Export JSON if requested
    if args.export_json:
        export_results_json(
            args.export_json,
            cpython_times,
            velo_times,
            cpython_label="CPython (Schema Generation)",
            velo_label="Velo (Pre-locked Schemas)"
        )


if __name__ == "__main__":
    main()
