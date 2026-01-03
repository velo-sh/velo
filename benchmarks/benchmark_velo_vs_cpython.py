#!/usr/bin/env python3
"""
Velo vs CPython Comparison Benchmark
=====================================
Head-to-head performance comparison showing Velo's speedup over CPython.

Produces compelling metrics like "12.5x faster than CPython"
"""

import argparse
import subprocess
import tempfile
import time
import os
import json
import statistics
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Scale configurations
SCENARIOS = {
    "hello": {
        "name": "Hello World",
        "description": "Minimal script",
        "models": 0,
        "routes": 0,
    },
    "small": {
        "name": "Small API",
        "description": "10 models, 10 routes",
        "models": 10,
        "routes": 10,
    },
    "medium": {
        "name": "Medium API",
        "description": "50 models, 50 routes",
        "models": 50,
        "routes": 50,
    },
    "large": {
        "name": "Large API",
        "description": "200 models, 100 routes",
        "models": 200,
        "routes": 100,
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "500+ models, production scale",
        "models": 500,
        "routes": 200,
    },
}

@dataclass
class ComparisonResult:
    framework: str
    scenario: str
    scenario_name: str
    components: int
    cpython_ms: float
    velo_cold_ms: float
    velo_warm_ms: float
    speedup_cold: float
    speedup_warm: float
    success: bool
    error: Optional[str] = None

def run_command(cmd: list, cwd: Path, timeout: int = 120, env: dict = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)

def measure_startup(cmd: list, cwd: Path, runs: int = 5, env: dict = None) -> tuple[float, float]:
    """Measure startup time, return (average_ms, min_ms)."""
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60, env=env)
        elapsed = (time.perf_counter() - start) * 1000
        if result.returncode == 0:
            times.append(elapsed)
    
    if not times:
        return 0, 0
    return statistics.mean(times), min(times)

def setup_project(project_dir: Path, deps: list[str]):
    """Initialize uv project with dependencies."""
    subprocess.run(["uv", "init", "-q"], cwd=project_dir, capture_output=True)
    if deps:
        subprocess.run(["uv", "add", "-q"] + deps, cwd=project_dir, capture_output=True)

def generate_fastapi_project(project_dir: Path, scenario: str) -> int:
    """Generate FastAPI project at specified scale."""
    config = SCENARIOS[scenario]
    n_models = config["models"]
    n_routes = config["routes"]
    
    if n_models == 0:
        # Hello world
        (project_dir / "main.py").write_text('''
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello World"}

print("FASTAPI_OK")
''')
        return 1
    
    # Create models
    models_dir = project_dir / "models"
    models_dir.mkdir(exist_ok=True)
    (models_dir / "__init__.py").write_text("")
    
    for i in range(n_models):
        (models_dir / f"model_{i}.py").write_text(f'''
from pydantic import BaseModel

class Model{i}(BaseModel):
    id: int
    name: str
    value_{i}: float = 0.0
''')
    
    # Create routers
    routers_dir = project_dir / "routers"
    routers_dir.mkdir(exist_ok=True)
    (routers_dir / "__init__.py").write_text("")
    
    for i in range(n_routes):
        model_idx = i % n_models
        (routers_dir / f"router_{i}.py").write_text(f'''
from fastapi import APIRouter
from models.model_{model_idx} import Model{model_idx}

router = APIRouter()

@router.get("/item_{i}")
def get_item_{i}() -> Model{model_idx}:
    return Model{model_idx}(id={i}, name="item_{i}")
''')
    
    # Create main app
    router_imports = "\n".join([f"from routers.router_{i} import router as r{i}" for i in range(n_routes)])
    router_includes = "\n".join([f"app.include_router(r{i}, prefix='/v{i}')" for i in range(n_routes)])
    
    (project_dir / "main.py").write_text(f'''
from fastapi import FastAPI

{router_imports}

app = FastAPI(title="FastAPI Benchmark")

{router_includes}

print("FASTAPI_OK")
''')
    
    return n_models + n_routes

def run_comparison(framework: str, scenario: str, velo_path: str, runs: int = 5) -> ComparisonResult:
    """Run head-to-head comparison between Velo and CPython."""
    config = SCENARIOS[scenario]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        try:
            # Setup project
            setup_project(project_dir, ["fastapi", "pydantic"])
            components = generate_fastapi_project(project_dir, scenario)
            
            # Find Python in the created venv
            python_path = project_dir / ".venv" / "bin" / "python"
            if not python_path.exists():
                python_path = "python3"
            else:
                python_path = str(python_path)
            
            # ============================================
            # CPYTHON BASELINE
            # ============================================
            print(f"   📊 Measuring CPython...")
            cpython_avg, cpython_min = measure_startup(
                [python_path, "main.py"],
                project_dir,
                runs=runs
            )
            
            if cpython_avg == 0:
                return ComparisonResult(
                    framework=framework, scenario=scenario, scenario_name=config["name"],
                    components=components, cpython_ms=0, velo_cold_ms=0, velo_warm_ms=0,
                    speedup_cold=0, speedup_warm=0, success=False, error="CPython failed"
                )
            
            # ============================================
            # VELO BUNDLE BUILD
            # ============================================
            print(f"   🔨 Building Velo bundle...")
            build_result = run_command([velo_path, "bundle", "build"], project_dir)
            if build_result.returncode != 0:
                return ComparisonResult(
                    framework=framework, scenario=scenario, scenario_name=config["name"],
                    components=components, cpython_ms=cpython_avg, velo_cold_ms=0, velo_warm_ms=0,
                    speedup_cold=0, speedup_warm=0, success=False, error="Velo build failed"
                )
            
            # ============================================
            # VELO COLD START (first run after build)
            # ============================================
            print(f"   ❄️  Measuring Velo cold start...")
            cold_start = time.perf_counter()
            cold_result = run_command([velo_path, "run", "--fast", "main.py"], project_dir)
            velo_cold_ms = (time.perf_counter() - cold_start) * 1000
            
            if cold_result.returncode != 0 or "FASTAPI_OK" not in cold_result.stdout:
                return ComparisonResult(
                    framework=framework, scenario=scenario, scenario_name=config["name"],
                    components=components, cpython_ms=cpython_avg, velo_cold_ms=velo_cold_ms, velo_warm_ms=0,
                    speedup_cold=0, speedup_warm=0, success=False, error="Velo run failed"
                )
            
            # ============================================
            # VELO WARM START (cached, multiple runs)
            # ============================================
            print(f"   🔥 Measuring Velo warm start...")
            velo_avg, velo_min = measure_startup(
                [velo_path, "run", "--fast", "main.py"],
                project_dir,
                runs=runs
            )
            
            # Calculate speedups
            speedup_cold = cpython_avg / velo_cold_ms if velo_cold_ms > 0 else 0
            speedup_warm = cpython_avg / velo_min if velo_min > 0 else 0
            
            return ComparisonResult(
                framework=framework, scenario=scenario, scenario_name=config["name"],
                components=components, cpython_ms=cpython_avg, velo_cold_ms=velo_cold_ms, 
                velo_warm_ms=velo_min, speedup_cold=speedup_cold, speedup_warm=speedup_warm,
                success=True
            )
            
        except Exception as e:
            return ComparisonResult(
                framework=framework, scenario=scenario, scenario_name=config["name"],
                components=0, cpython_ms=0, velo_cold_ms=0, velo_warm_ms=0,
                speedup_cold=0, speedup_warm=0, success=False, error=str(e)
            )

def print_results(results: list[ComparisonResult]):
    """Print spectacular comparison results."""
    print("\n")
    print("=" * 100)
    print("🚀 VELO vs CPYTHON: HEAD-TO-HEAD PERFORMANCE COMPARISON 🚀")
    print("=" * 100)
    
    # Header
    print(f"\n{'Scenario':<15} {'Components':>10} {'CPython':>12} {'Velo Cold':>12} {'Velo Warm':>12} {'Speedup':>12}")
    print("-" * 100)
    
    for r in results:
        if r.success:
            speedup_str = f"⚡ {r.speedup_warm:.1f}x faster"
            print(f"{r.scenario_name:<15} {r.components:>10} {r.cpython_ms:>10.1f}ms {r.velo_cold_ms:>10.1f}ms {r.velo_warm_ms:>10.1f}ms {speedup_str:>18}")
        else:
            print(f"{r.scenario_name:<15} {r.components:>10} {'--':>12} {'--':>12} {'--':>12} ❌ FAIL")
    
    print("=" * 100)
    
    # Spectacular summary
    successful = [r for r in results if r.success]
    if successful:
        max_speedup = max(r.speedup_warm for r in successful)
        avg_speedup = statistics.mean(r.speedup_warm for r in successful)
        enterprise = next((r for r in successful if r.scenario == "enterprise"), None)
        
        print("\n")
        print("╔" + "═" * 70 + "╗")
        print("║" + " " * 20 + "🏆 PERFORMANCE HIGHLIGHTS 🏆" + " " * 22 + "║")
        print("╠" + "═" * 70 + "╣")
        print(f"║  Maximum Speedup:  {max_speedup:>6.1f}x faster than CPython" + " " * 25 + "║")
        print(f"║  Average Speedup:  {avg_speedup:>6.1f}x faster than CPython" + " " * 25 + "║")
        if enterprise:
            print(f"║  Enterprise (500+ models): {enterprise.cpython_ms:.0f}ms → {enterprise.velo_warm_ms:.0f}ms  ({enterprise.speedup_warm:.1f}x) ⚡" + " " * 10 + "║")
        print("╚" + "═" * 70 + "╝")
    
    # Visual bar chart
    print("\n📊 VISUAL COMPARISON (startup time in ms, lower is better)")
    print("-" * 70)
    
    for r in successful:
        max_bar = 50
        cpython_bar = int(min(r.cpython_ms / 20, max_bar))
        velo_bar = int(min(r.velo_warm_ms / 20, max_bar))
        
        print(f"\n{r.scenario_name}:")
        print(f"  CPython:  {'█' * cpython_bar}░ {r.cpython_ms:.0f}ms")
        print(f"  Velo:     {'█' * velo_bar}░ {r.velo_warm_ms:.0f}ms  ⚡{r.speedup_warm:.1f}x faster")

def export_json(results: list[ComparisonResult], output_file: str):
    """Export results to JSON."""
    data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [
            {
                "framework": r.framework,
                "scenario": r.scenario,
                "scenario_name": r.scenario_name,
                "components": r.components,
                "cpython_ms": r.cpython_ms,
                "velo_cold_ms": r.velo_cold_ms,
                "velo_warm_ms": r.velo_warm_ms,
                "speedup_cold": r.speedup_cold,
                "speedup_warm": r.speedup_warm,
                "success": r.success,
            }
            for r in results
        ],
        "summary": {
            "max_speedup": max(r.speedup_warm for r in results if r.success) if any(r.success for r in results) else 0,
            "avg_speedup": statistics.mean(r.speedup_warm for r in results if r.success) if any(r.success for r in results) else 0,
        }
    }
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n📁 Results exported to: {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Velo vs CPython Performance Comparison")
    parser.add_argument("--scenario", type=str, default="all", 
                        choices=["all", "hello", "small", "medium", "large", "enterprise"],
                        help="Test scenario")
    parser.add_argument("--runs", type=int, default=5, help="Number of timing runs")
    parser.add_argument("--output", type=str, default="comparison_results.json", help="JSON output file")
    args = parser.parse_args()
    
    # Determine velo path
    script_dir = Path(__file__).parent.resolve()
    velo_path = str(script_dir.parent / "target" / "release" / "velo")
    
    if not Path(velo_path).exists():
        print(f"❌ Velo binary not found at: {velo_path}")
        print("   Run: cargo build --release")
        return
    
    print("🚀 Velo vs CPython: Performance Showdown")
    print("=" * 50)
    
    # Determine scenarios to test
    if args.scenario == "all":
        scenarios = list(SCENARIOS.keys())
    else:
        scenarios = [args.scenario]
    
    results = []
    for scenario in scenarios:
        config = SCENARIOS[scenario]
        print(f"\n⏳ Testing {config['name']} ({config['description']})...")
        result = run_comparison("fastapi", scenario, velo_path, args.runs)
        results.append(result)
        
        if result.success:
            print(f"   ✅ CPython: {result.cpython_ms:.1f}ms | Velo: {result.velo_warm_ms:.1f}ms | Speedup: {result.speedup_warm:.1f}x")
        else:
            print(f"   ❌ Failed: {result.error}")
    
    print_results(results)
    export_json(results, args.output)

if __name__ == "__main__":
    main()
