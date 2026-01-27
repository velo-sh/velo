#!/usr/bin/env python3
"""
Framework Scaling Benchmark Suite
==================================
Tests FastAPI, Flask, Django at progressive scales from "Hello World" to "Enterprise".

Scale Levels:
- L1: Hello World (1-5 components) - Baseline
- L2: Small App (10-20 components) - Starter project
- L3: Medium App (50-100 components) - Growing project
- L4: Large App (200-500 components) - Production app
- L5: Enterprise (500-1000+ components) - Monolith stress test

Usage:
    python3 benchmark_framework_scale.py --all
    python3 benchmark_framework_scale.py --fastapi --level L3
    python3 benchmark_framework_scale.py --django --level L5
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Scale configurations
SCALE_LEVELS = {
    "L1": {"name": "Hello World", "models": 1, "routes": 1, "apps": 1, "blueprints": 1},
    "L2": {
        "name": "Small App",
        "models": 10,
        "routes": 10,
        "apps": 5,
        "blueprints": 10,
    },
    "L3": {
        "name": "Medium App",
        "models": 50,
        "routes": 50,
        "apps": 20,
        "blueprints": 50,
    },
    "L4": {
        "name": "Large App",
        "models": 200,
        "routes": 100,
        "apps": 50,
        "blueprints": 100,
    },
    "L5": {
        "name": "Enterprise",
        "models": 500,
        "routes": 200,
        "apps": 100,
        "blueprints": 200,
    },
}


@dataclass
class BenchmarkResult:
    framework: str
    level: str
    scale_name: str
    components: int
    build_time_ms: float
    load_time_ms: float
    success: bool
    error: str | None = None


def run_command(cmd: list, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def setup_project(project_dir: Path, deps: list[str]):
    """Initialize uv project with dependencies."""
    subprocess.run(["uv", "init", "-q"], cwd=project_dir, capture_output=True)
    if deps:
        subprocess.run(["uv", "add", "-q"] + deps, cwd=project_dir, capture_output=True)


# ============================================================================
# FastAPI Generator
# ============================================================================
def generate_fastapi_project(project_dir: Path, level: str) -> int:
    """Generate FastAPI project at specified scale."""
    config = SCALE_LEVELS[level]
    n_models = config["models"]
    n_routes = config["routes"]

    # Create models
    models_dir = project_dir / "models"
    models_dir.mkdir(exist_ok=True)
    (models_dir / "__init__.py").write_text("")

    for i in range(n_models):
        (models_dir / f"model_{i}.py").write_text(
            f"""
from pydantic import BaseModel

class Model{i}(BaseModel):
    id: int
    name: str
    value_{i}: float = 0.0
"""
        )

    # Create routers
    routers_dir = project_dir / "routers"
    routers_dir.mkdir(exist_ok=True)
    (routers_dir / "__init__.py").write_text("")

    for i in range(n_routes):
        model_idx = i % n_models
        (routers_dir / f"router_{i}.py").write_text(
            f"""
from fastapi import APIRouter
from models.model_{model_idx} import Model{model_idx}

router = APIRouter()

@router.get("/item_{i}")
def get_item_{i}() -> Model{model_idx}:
    return Model{model_idx}(id={i}, name="item_{i}")
"""
        )

    # Create main app
    router_imports = "\n".join([f"from routers.router_{i} import router as r{i}" for i in range(n_routes)])
    router_includes = "\n".join([f"app.include_router(r{i}, prefix='/v{i}')" for i in range(n_routes)])

    (project_dir / "main.py").write_text(
        f"""
from fastapi import FastAPI

{router_imports}

app = FastAPI(title="FastAPI Benchmark {level}")

{router_includes}

print("FASTAPI_{level}_OK")
"""
    )

    return n_models + n_routes


def generate_flask_project(project_dir: Path, level: str) -> int:
    """Generate Flask project at specified scale."""
    config = SCALE_LEVELS[level]
    n_blueprints = config["blueprints"]

    # Create blueprints
    bp_dir = project_dir / "blueprints"
    bp_dir.mkdir(exist_ok=True)
    (bp_dir / "__init__.py").write_text("")

    for i in range(n_blueprints):
        (bp_dir / f"bp_{i}.py").write_text(
            f"""
from flask import Blueprint, jsonify

bp_{i} = Blueprint('bp_{i}', __name__, url_prefix='/bp{i}')

@bp_{i}.route('/status')
def status_{i}():
    return jsonify({{"blueprint": {i}, "status": "ok"}})

@bp_{i}.route('/data')
def data_{i}():
    return jsonify({{"items": list(range({i}, {i}+10))}})
"""
        )

    # Create main app
    bp_imports = "\n".join([f"from blueprints.bp_{i} import bp_{i}" for i in range(n_blueprints)])
    bp_registers = "\n".join([f"app.register_blueprint(bp_{i})" for i in range(n_blueprints)])

    (project_dir / "main.py").write_text(
        f"""
from flask import Flask

app = Flask(__name__)

{bp_imports}

{bp_registers}

print("FLASK_{level}_OK")
"""
    )

    return n_blueprints


def generate_django_project(project_dir: Path, level: str) -> int:
    """Generate Django project at specified scale."""
    config = SCALE_LEVELS[level]
    n_apps = config["apps"]

    # Create settings
    installed_apps = ", ".join([f"'app_{i}'" for i in range(n_apps)])
    (project_dir / "settings.py").write_text(
        f"""
SECRET_KEY = 'benchmark-secret-{level}'
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    {installed_apps}
]
DATABASES = {{'default': {{'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
"""
    )

    # Create apps
    for i in range(n_apps):
        app_dir = project_dir / f"app_{i}"
        app_dir.mkdir(exist_ok=True)

        (app_dir / "__init__.py").write_text("")

        (app_dir / "apps.py").write_text(
            f"""
from django.apps import AppConfig

class App{i}Config(AppConfig):
    name = 'app_{i}'
    default_auto_field = 'django.db.models.BigAutoField'
"""
        )

        (app_dir / "models.py").write_text(
            f"""
from django.db import models

class Entity{i}(models.Model):
    name = models.CharField(max_length=100)
    value = models.IntegerField(default={i})

    class Meta:
        app_label = 'app_{i}'
"""
        )

    # Create main
    (project_dir / "main.py").write_text(
        f"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

print("DJANGO_{level}_OK")
"""
    )

    return n_apps


# ============================================================================
# Benchmark Runner
# ============================================================================
def run_benchmark(framework: str, level: str, velo_path: str) -> BenchmarkResult:
    """Run benchmark for a specific framework at a specific scale level."""
    config = SCALE_LEVELS[level]

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        try:
            # Setup project
            if framework == "fastapi":
                setup_project(project_dir, ["fastapi", "pydantic"])
                components = generate_fastapi_project(project_dir, level)
            elif framework == "flask":
                setup_project(project_dir, ["flask"])
                components = generate_flask_project(project_dir, level)
            elif framework == "django":
                setup_project(project_dir, ["django"])
                components = generate_django_project(project_dir, level)
            else:
                raise ValueError(f"Unknown framework: {framework}")

            # Build bundle
            start_build = time.perf_counter()
            build_result = run_command([velo_path, "bundle", "build"], project_dir)
            build_time_ms = (time.perf_counter() - start_build) * 1000

            if build_result.returncode != 0:
                return BenchmarkResult(
                    framework=framework,
                    level=level,
                    scale_name=config["name"],
                    components=components,
                    build_time_ms=build_time_ms,
                    load_time_ms=0,
                    success=False,
                    error=f"Build failed: {build_result.stderr[:200]}",
                )

            # Run with fast loader (5 runs, take average)
            load_times = []
            for _ in range(5):
                env = os.environ.copy()
                env["VELO_REPORT_METRICS"] = "1"

                start_run = time.perf_counter()
                run_result = run_command([velo_path, "run", "--fast", "main.py"], project_dir)
                run_time_ms = (time.perf_counter() - start_run) * 1000
                load_times.append(run_time_ms)

                expected_output = f"{framework.upper()}_{level}_OK"
                if expected_output not in run_result.stdout:
                    return BenchmarkResult(
                        framework=framework,
                        level=level,
                        scale_name=config["name"],
                        components=components,
                        build_time_ms=build_time_ms,
                        load_time_ms=run_time_ms,
                        success=False,
                        error=f"Run failed or wrong output. Got: {run_result.stdout[:100]}",
                    )

            avg_load_time = sum(load_times) / len(load_times)

            return BenchmarkResult(
                framework=framework,
                level=level,
                scale_name=config["name"],
                components=components,
                build_time_ms=build_time_ms,
                load_time_ms=avg_load_time,
                success=True,
            )

        except Exception as e:
            return BenchmarkResult(
                framework=framework,
                level=level,
                scale_name=config["name"],
                components=0,
                build_time_ms=0,
                load_time_ms=0,
                success=False,
                error=str(e),
            )


def print_results(results: list[BenchmarkResult]):
    """Print benchmark results in a formatted table."""
    print("\n" + "=" * 90)
    print("🎯 FRAMEWORK SCALING BENCHMARK RESULTS")
    print("=" * 90)
    print(
        f"{'Framework':<12} {'Level':<5} {'Scale':<15} {'Components':>10} {'Build (ms)':>12} {'Load (ms)':>12} {'Status':<8}"
    )
    print("-" * 90)

    for r in results:
        status = "✅ PASS" if r.success else "❌ FAIL"
        if r.success:
            print(
                f"{r.framework:<12} {r.level:<5} {r.scale_name:<15} {r.components:>10} {r.build_time_ms:>12.1f} {r.load_time_ms:>12.1f} {status:<8}"
            )
        else:
            print(
                f"{r.framework:<12} {r.level:<5} {r.scale_name:<15} {r.components:>10} {'--':>12} {'--':>12} {status:<8}"
            )
            print(f"    Error: {r.error[:70]}...")

    print("=" * 90)


def export_json(results: list[BenchmarkResult], output_file: str):
    """Export results to JSON for CI integration."""
    data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [
            {
                "framework": r.framework,
                "level": r.level,
                "scale_name": r.scale_name,
                "components": r.components,
                "build_time_ms": r.build_time_ms,
                "load_time_ms": r.load_time_ms,
                "success": r.success,
                "error": r.error,
            }
            for r in results
        ],
    }
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n📁 Results exported to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Framework Scaling Benchmark Suite")
    parser.add_argument("--fastapi", action="store_true", help="Benchmark FastAPI")
    parser.add_argument("--flask", action="store_true", help="Benchmark Flask")
    parser.add_argument("--django", action="store_true", help="Benchmark Django")
    parser.add_argument("--all", action="store_true", help="Benchmark all frameworks")
    parser.add_argument("--level", type=str, default="all", help="Scale level (L1-L5 or 'all')")
    parser.add_argument("--output", type=str, default="benchmark_results.json", help="JSON output file")
    args = parser.parse_args()

    # Determine velo path
    script_dir = Path(__file__).parent.resolve()
    velo_path = str(script_dir / "target" / "release" / "velo")

    if not Path(velo_path).exists():
        print(f"❌ Velo binary not found at: {velo_path}")
        print("   Run: cargo build --release")
        return

    # Determine frameworks to test
    frameworks = []
    if args.all:
        frameworks = ["fastapi", "flask", "django"]
    else:
        if args.fastapi:
            frameworks.append("fastapi")
        if args.flask:
            frameworks.append("flask")
        if args.django:
            frameworks.append("django")

    if not frameworks:
        frameworks = ["fastapi", "flask", "django"]  # Default: all

    # Determine levels to test
    if args.level == "all":
        levels = list(SCALE_LEVELS.keys())
    else:
        levels = [args.level.upper()]

    print("🚀 Starting Framework Scaling Benchmarks...")
    print(f"   Frameworks: {', '.join(frameworks)}")
    print(f"   Levels: {', '.join(levels)}")

    results = []
    for framework in frameworks:
        for level in levels:
            print(f"\n⏳ Testing {framework.upper()} @ {level} ({SCALE_LEVELS[level]['name']})...")
            result = run_benchmark(framework, level, velo_path)
            results.append(result)
            if result.success:
                print(f"   ✅ Build: {result.build_time_ms:.1f}ms | Load: {result.load_time_ms:.1f}ms")
            else:
                print(f"   ❌ Failed: {result.error[:50]}...")

    print_results(results)
    export_json(results, args.output)


if __name__ == "__main__":
    main()
