# Phase 6 Performance Regressions: Framework Scaling (FastAPI, Flask, Django)
# Tracks build/load latency to prevent regressions in Phase 6.0 Static Graph.

import pytest
import os
import json
from pathlib import Path

@pytest.mark.tier2
@pytest.mark.perf
class TestPhase6PerfRegressions:
    """Enterprise-scale performance regression suite for core frameworks."""

    @pytest.mark.parametrize("scale", ["medium", "large"])
    def test_PERF_602_fastapi_regression_scale(self, isolated_env, scale):
        """PERF-602: Track FastAPI + Pydantic build/load latency regression."""
        env = isolated_env
        env.install("fastapi", "pydantic")
        
        counts = {"medium": 50, "large": 500}
        n = counts[scale]
        
        # 1. Generate scaled project
        models = [f"class M{i}(BaseModel):\n    x: int = {i}" for i in range(n)]
        routes = [f"@app.get('/{i}')\ndef r{i}(): return M{i}()" for i in range(n)]
        
        models_str = "\n".join(models)
        routes_str = "\n".join(routes)
        
        env.create_app("main.py", f"""
from fastapi import FastAPI
from pydantic import BaseModel
app = FastAPI()
{models_str}
{routes_str}
""")
        
        # 2. Build and measure build_time_ms
        result_build = env.run_velo("bundle", "build")
        build_time = 0
        combined_output = result_build.stdout + result_build.stderr
        for line in combined_output.splitlines():
            if '"build_time_ms"' in line:
                try:
                    if line.strip().startswith("{"):
                        build_time = json.loads(line).get("build_time_ms", 0)
                    else:
                        start = combined_output.find("{", combined_output.find(line))
                        end = combined_output.find("}", start) + 1
                        build_time = json.loads(combined_output[start:end]).get("build_time_ms", 0)
                    break
                except (json.JSONDecodeError, ValueError):
                    continue
        
        # Thresholds: Medium < 50ms, Large < 200ms
        max_build = 50 if scale == "medium" else 200
        assert build_time < max_build, f"Build regression: {build_time}ms > {max_build}ms"

        # 3. Load and measure deserialize_latency_us
        env_vars = os.environ.copy()
        env_vars["VELO_REPORT_METRICS"] = "1"
        result_run = env.run_velo("run", "--fast", "main.py", env=env_vars)
        
        latency = 999999
        combined_run = result_run.stdout + result_run.stderr
        for line in combined_run.splitlines():
            if '"graph_deserialize_latency_us"' in line:
                try:
                    if line.strip().startswith("{"):
                        latency = json.loads(line).get("graph_deserialize_latency_us", 999999)
                    else:
                        start = combined_run.find("{", combined_run.find(line))
                        end = combined_run.find("}", start) + 1
                        latency = json.loads(combined_run[start:end]).get("graph_deserialize_latency_us", 999999)
                    break
                except (json.JSONDecodeError, ValueError):
                    continue
        
        # Threshold: < 1000us (1ms) even for 500 models
        assert latency < 1000, f"Load regression: {latency}μs > 1000μs"

    @pytest.mark.xfail(reason="P3: Flask metrics output missing graph_deserialize_latency_us (tracked in ARCH-60-001)")
    @pytest.mark.parametrize("scale", ["medium", "large"])
    def test_PERF_603_flask_regression_scale(self, isolated_env, scale):
        """PERF-603: Track Flask Blueprint scan latency regression."""
        env = isolated_env
        env.install("flask")
        
        counts = {"medium": 20, "large": 100}
        n = counts[scale]
        
        # 1. Generate scaled project
        for i in range(n):
            env.create_app(f"bp{i}.py", f"from flask import Blueprint\nbp = Blueprint('b{i}', __name__)")
        
        regs = [f"from bp{i} import bp as b{i}; app.register_blueprint(b{i})" for i in range(n)]
        env.create_app("main.py", f"from flask import Flask\napp = Flask(__name__)\n" + "\n".join(regs))
        
        # 2. Build
        result_build = env.run_velo("bundle", "build")
        
        # 3. Measure load performance
        env_vars = os.environ.copy()
        env_vars["VELO_REPORT_METRICS"] = "1"
        result_run = env.run_velo("run", "--fast", "main.py", env=env_vars)
        
        # 4. Parse metrics from both stdout and stderr (robust parsing)
        latency = 999999
        combined_output = result_run.stdout + result_run.stderr
        for line in combined_output.splitlines():
            if '"graph_deserialize_latency_us"' in line:
                try:
                    if line.strip().startswith("{"):
                        latency = json.loads(line).get("graph_deserialize_latency_us", 999999)
                    else:
                        start = combined_output.find("{", combined_output.find(line))
                        end = combined_output.find("}", start) + 1
                        latency = json.loads(combined_output[start:end]).get("graph_deserialize_latency_us", 999999)
                    break
                except (json.JSONDecodeError, ValueError):
                    continue
        
        assert latency < 1000, f"Flask load regression: {latency}μs"

    @pytest.mark.parametrize("scale", ["medium", "large"])
    def test_PERF_604_django_regression_scale(self, isolated_env, scale):
        """PERF-604: Track Django App Registry discovery regression."""
        env = isolated_env
        env.install("django")
        
        counts = {"medium": 10, "large": 50}
        n = counts[scale]
        
        # 1. Setup scaled Django
        apps = [f"a{i}" for i in range(n)]
        for a in apps:
            (env.path / a).mkdir(parents=True, exist_ok=True)
            env.create_app(f"{a}/__init__.py", "")
            env.create_app(f"{a}/models.py", "from django.db import models")
        
        env.create_app("settings.py", f"SECRET_KEY='f';INSTALLED_APPS={apps};DATABASES={{'default':{{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}}}")
        env.create_app("main.py", "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings'); django.setup()")
        
        # 2. Build
        env.run_velo("bundle", "build")
        
        # 3. Measure
        env_vars = os.environ.copy()
        env_vars["VELO_REPORT_METRICS"] = "1"
        result_run = env.run_velo("run", "--fast", "main.py", env=env_vars)
        
        latency = 999999
        for line in result_run.stderr.splitlines():
            if '"graph_deserialize_latency_us"' in line:
                latency = json.loads(line).get("graph_deserialize_latency_us", 999999)
                break
        
        assert latency < 2000, f"Django load regression: {latency}μs"
