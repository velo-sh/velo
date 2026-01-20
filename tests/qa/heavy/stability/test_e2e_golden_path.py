# E2E Golden Path: Framework Triad Correctness Suite
# Tests the complete user workflow: Build -> Load -> Run -> Verify Output
# This is the CORRECTNESS gate - performance is secondary.

from pathlib import Path

import pytest

# --- Project Templates (Simulating Real User Projects) ---

FASTAPI_PROJECT = {
    "deps": ["fastapi", "pydantic"],
    "files": {
        "main.py": """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI"}

# This line is executed when the module is imported
print("FASTAPI_GOLDEN_OUTPUT")
""",
    },
    "expected_output": "FASTAPI_GOLDEN_OUTPUT",
}

FLASK_PROJECT = {
    "deps": ["flask"],
    "files": {
        "main.py": """
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def hello():
    return jsonify(message="Hello from Flask")

# This line is executed when the module is imported
print("FLASK_GOLDEN_OUTPUT")
""",
    },
    "expected_output": "FLASK_GOLDEN_OUTPUT",
}

DJANGO_PROJECT = {
    "deps": ["django"],
    "files": {
        "settings.py": """
SECRET_KEY = 'golden-path-secret'
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.auth']
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
""",
        "main.py": """
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from django.http import HttpResponse

def hello(request):
    return HttpResponse("Hello from Django")

# This line is executed when the module is imported
print("DJANGO_GOLDEN_OUTPUT")
""",
    },
    "expected_output": "DJANGO_GOLDEN_OUTPUT",
}

FRAMEWORK_PROJECTS = {
    "fastapi": FASTAPI_PROJECT,
    "flask": FLASK_PROJECT,
    "django": DJANGO_PROJECT,
}


@pytest.mark.e2e
@pytest.mark.correctness
class TestE2EGoldenPath:
    """E2E Correctness Suite: Verify complete user workflow for Big Three frameworks."""

    def setup_project(self, env, project_config):
        """Setup a real project structure with dependencies."""
        env.install(*project_config["deps"])
        for filename, content in project_config["files"].items():
            # Handle nested directories
            filepath = Path(filename)
            if filepath.parent != Path("."):
                (env.path / filepath.parent).mkdir(parents=True, exist_ok=True)
            env.create_app(filename, content)

    @pytest.mark.parametrize("framework", ["fastapi", "flask", "django"])
    def test_GOLD_001_triad_full_cycle(self, isolated_env, framework):
        """GOLD-001: Full E2E cycle for each framework."""
        env = isolated_env
        project = FRAMEWORK_PROJECTS[framework]

        # 1. Setup project
        self.setup_project(env, project)

        # 2. Build bundle
        build_result = env.run_velo("bundle", "build")
        assert build_result.returncode == 0, f"Build failed for {framework}: {build_result.stderr}"
        assert (env.path / "bundle.veloc").exists(), f"Bundle not created for {framework}"

        # 3. Run with fast loader
        run_result = env.run_velo("run", "--fast", "main.py")

        # 4. Verify NO fallback (critical!)
        assert "Fast loader failed" not in run_result.stdout, (
            f"Fast loader fallback for {framework}: {run_result.stdout}"
        )

        # 5. Verify business logic output (THE MOST IMPORTANT CHECK)
        assert project["expected_output"] in run_result.stdout, (
            f"Business logic failed for {framework}. Expected '{project['expected_output']}' in stdout: {run_result.stdout}"
        )

        # 6. Verify clean exit
        assert run_result.returncode == 0, f"Non-zero exit for {framework}: {run_result.returncode}"

    @pytest.mark.parametrize("framework", ["fastapi", "flask", "django"])
    def test_GOLD_002_rebuild_idempotency(self, isolated_env, framework):
        """GOLD-002: Rebuilding produces identical behavior."""
        env = isolated_env
        project = FRAMEWORK_PROJECTS[framework]
        self.setup_project(env, project)

        # Build and run twice
        env.run_velo("bundle", "build")
        run1 = env.run_velo("run", "--fast", "main.py")

        env.run_velo("bundle", "build")  # Rebuild
        run2 = env.run_velo("run", "--fast", "main.py")

        # Both runs should produce identical output
        assert run1.stdout == run2.stdout, (
            f"Non-idempotent behavior for {framework}: '{run1.stdout}' != '{run2.stdout}'"
        )

    @pytest.mark.parametrize("framework", ["fastapi", "flask", "django"])
    def test_GOLD_003_no_bundle_fallback(self, isolated_env, framework):
        """GOLD-003: Without bundle, velo run still works (fallback to CPython)."""
        env = isolated_env
        project = FRAMEWORK_PROJECTS[framework]
        self.setup_project(env, project)

        # Run WITHOUT building bundle first
        run_result = env.run_velo("run", "main.py")

        # Should still succeed via CPython fallback
        assert run_result.returncode == 0, f"CPython fallback failed for {framework}"
        assert project["expected_output"] in run_result.stdout, f"CPython fallback output incorrect for {framework}"
