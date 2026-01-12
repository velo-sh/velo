#!/usr/bin/env python3
"""
Enterprise-Scale Benchmarks for Velo.
Simulates real-world "Heavyweight" project structures for FastAPI, Flask, and Django.
"""

import subprocess
import shutil
import time
import argparse
import os
import json
from pathlib import Path

VELO_BIN = Path(__file__).parent / "target/release/velo"
BENCH_ROOT = Path(__file__).parent.parent / "velo-enterprise-benchmarks"


class EnterpriseGenerator:
    """Generates complex, multi-file 'Enterprise' projects."""

    @staticmethod
    def create_fastapi(path: Path, modules=500):
        """Heavyweight FastAPI: 500+ models, 50+ routers, deep nesting."""
        print(f"  Generating FastAPI Enterprise ({modules} modules)...")
        app_dir = path / "app"
        app_dir.mkdir(parents=True)

        # 1. Models Layer (Pydantic Heavy)
        models_dir = app_dir / "models"
        models_dir.mkdir()
        for i in range(10):  # 10 model files
            code = ["from pydantic import BaseModel", "from typing import Optional"]
            for j in range(modules // 10):
                code.append(
                    f"class Model_{i}_{j}(BaseModel):\n    id: int\n    name: str\n    meta: Optional[dict] = None"
                )
            (models_dir / f"m{i}.py").write_text("\n".join(code))
        (models_dir / "__init__.py").write_text(
            "".join([f"from .m{i} import *\n" for i in range(10)])
        )

        # 2. Routers Layer
        routers_dir = app_dir / "internal"
        routers_dir.mkdir()
        for i in range(20):
            code = [
                f"from fastapi import APIRouter\nfrom ..models.m{i % 10} import Model_{i % 10}_0",
                f"router = APIRouter()",
            ]
            code.append(
                f"@router.get('/{i}')\ndef route_{i}(): return Model_{i % 10}_0(id={i}, name='test')"
            )
            (routers_dir / f"r{i}.py").write_text("\n".join(code))

        # 3. Main Entry
        main_code = [
            "from fastapi import FastAPI",
            "from .internal import " + ", ".join([f"r{i}" for i in range(20)]),
        ]
        main_code.append("app = FastAPI()")
        for i in range(20):
            main_code.append(f"app.include_router(r{i}.router)")
        main_code.append("@app.get('/')\ndef root(): return {'status': 'heavy'}")
        (app_dir / "main.py").write_text("\n".join(main_code))
        (app_dir / "__init__.py").write_text("")

        # 4. Root Wrapper (for velo run)
        (path / "entry.py").write_text(
            "from app.main import app\nprint('Enterprise FastAPI Start')"
        )

    @staticmethod
    def create_django(path: Path, apps=50):
        """Heavyweight Django: 50 apps, 200+ models, complex registry."""
        print(f"  Generating Django Monolith ({apps} apps)...")
        project_name = "monolith"

        # 1. Create 50 Apps
        installed_apps = []
        for i in range(apps):
            app_name = f"app_{i}"
            app_dir = path / app_name
            app_dir.mkdir()
            (app_dir / "__init__.py").write_text("")
            (app_dir / "models.py").write_text(
                f"from django.db import models\nclass Model_{i}(models.Model):\n    name = models.CharField(max_length=100)"
            )
            (app_dir / "views.py").write_text(
                f"from django.http import HttpResponse\nfrom .models import Model_{i}\ndef v_{i}(r): return HttpResponse('ok')"
            )
            installed_apps.append(app_name)

        # 2. Settings
        (path / "settings.py").write_text(
            f"""
SECRET_KEY = 'secret'
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.auth'] + {installed_apps}
DATABASES = {{'default': {{'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}}}
"""
        )

        # 3. Entry
        (path / "entry.py").write_text(
            """
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()
print('Enterprise Django Monolith Ready')
"""
        )

    @staticmethod
    def create_flask(path: Path, blueprints=50):
        """Heavyweight Flask: 50 blueprints, nested imports, extension simulation."""
        print(f"  Generating Flask Enterprise ({blueprints} blueprints)...")
        app_dir = path / "app"
        app_dir.mkdir(parents=True)

        # 1. Create Blueprints
        bp_dir = app_dir / "modules"
        bp_dir.mkdir()
        for i in range(blueprints):
            code = [
                "from flask import Blueprint, jsonify",
                f"bp_{i} = Blueprint('bp_{i}', __name__)",
                f"@bp_{i}.route('/{i}')",
                f"def route_{i}(): return jsonify(status='ok {i}')",
            ]
            # Add a vertical import (dependency between blueprints)
            if i > 0:
                code.insert(0, f"from .module_{i-1} import bp_{i-1}")
            (bp_dir / f"module_{i}.py").write_text("\n".join(code))

        (bp_dir / "__init__.py").write_text(
            "".join([f"from .module_{i} import bp_{i}\n" for i in range(blueprints)])
        )

        # 2. Main Entry
        main_code = [
            "from flask import Flask",
            "from .modules import " + ", ".join([f"bp_{i}" for i in range(blueprints)]),
            "app = Flask(__name__)",
        ]
        for i in range(blueprints):
            main_code.append(f"app.register_blueprint(bp_{i})")
        main_code.append("@app.get('/')\ndef index(): return 'Flask Lite'")
        (app_dir / "main.py").write_text("\n".join(main_code))
        (app_dir / "__init__.py").write_text("")

        # 3. Entry point
        (path / "entry.py").write_text(
            "from app.main import app\nprint('Enterprise Flask Ready')"
        )


def run_bench(name: Path, iterations=5):
    """Run benchmark comparison."""
    print(f"\nBenchmark: {name.name}")
    script = name / "entry.py"
    python = name / ".venv/bin/python"

    # Measure Velo (with metrics)
    env = os.environ.copy()
    env["VELO_REPORT_METRICS"] = "1"

    # Build
    start_build = time.perf_counter()
    subprocess.run([VELO_BIN, "bundle", "build"], cwd=name, capture_output=True)
    build_ms = (time.perf_counter() - start_build) * 1000

    # Warmup + Sync
    subprocess.run([VELO_BIN, "run", "--fast", script], cwd=name, capture_output=True)

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        subprocess.run(
            [VELO_BIN, "run", "--fast", script], cwd=name, capture_output=True, env=env
        )
        times.append((time.perf_counter() - start) * 1000)

    avg = sum(times) / len(times)
    print(f"  Build Time: {build_ms:6.1f}ms")
    print(f"  Load Time:  {avg:6.1f}ms (avg of {iterations})")


def setup_project(name: str, deps: list):
    """Common project setup."""
    p = BENCH_ROOT / name
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)
    (p / ".python-version").write_text("3.11\n")
    subprocess.run(
        ["uv", "init", "--no-workspace", "--name", name], cwd=p, capture_output=True
    )
    subprocess.run(["uv", "add"] + deps, cwd=p, capture_output=True)
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fastapi", action="store_true")
    parser.add_argument("--django", action="store_true")
    parser.add_argument("--flask", action="store_true")
    args = parser.parse_args()

    BENCH_ROOT.mkdir(parents=True, exist_ok=True)

    if args.fastapi:
        p = setup_project("enterprise_fastapi", ["fastapi", "pydantic", "uvicorn"])
        EnterpriseGenerator.create_fastapi(p)
        run_bench(p)

    if args.django:
        p = setup_project("enterprise_django", ["django"])
        EnterpriseGenerator.create_django(p)
        run_bench(p)

    if args.flask:
        p = setup_project("enterprise_flask", ["flask"])
        EnterpriseGenerator.create_flask(p)
        run_bench(p)


if __name__ == "__main__":
    main()
