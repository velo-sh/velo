import json
import os
import subprocess
from pathlib import Path

import pytest


def get_velo_binary():
    repo_root = Path(__file__).parent.parent.parent
    debug = repo_root / "target" / "debug" / "velo"
    release = repo_root / "target" / "release" / "velo"

    if debug.exists():
        return str(debug)
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


def test_r1_virtualenv_priority(tmp_path):
    # Setup: Create two "virtualenvs"
    venv1 = tmp_path / "venv1"
    venv1.mkdir()
    (venv1 / "bin").mkdir()
    python1 = venv1 / "bin" / "python"
    python1.write_text("#!/bin/sh\necho 'python1'")
    python1.chmod(0o755)

    venv2 = tmp_path / ".venv"
    venv2.mkdir()
    (venv2 / "bin").mkdir()
    python2 = venv2 / "bin" / "python"
    python2.write_text("#!/bin/sh\necho 'python2'")
    python2.chmod(0o755)

    # Run with VIRTUAL_ENV=venv1
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(venv1)

    velo_bin = get_velo_binary()

    # We use velo serve --dry-run to see which python it picks
    result = subprocess.run(
        [velo_bin, "serve", "main:app", "--dry-run"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    # The dry run output should show the path to python1
    assert str(python1) in result.stderr


def test_r2_django_inference(tmp_path):
    # Setup: Create a Django-like structure
    myproj = tmp_path / "myproj"
    myproj.mkdir()
    (myproj / "__init__.py").touch()
    (myproj / "settings.py").touch()
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = ['django']\n")
    (tmp_path / "main.py").write_text("app = None")  # Dummy app

    velo_bin = get_velo_binary()

    # Run velo serve --dry-run
    result = subprocess.run(
        [velo_bin, "serve", "main:app", "--dry-run", "-vv"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "Inferred DJANGO_SETTINGS_MODULE=myproj.settings" in result.stderr


def test_r3_json_logging_timing(tmp_path):
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")

    velo_bin = get_velo_binary()

    result = subprocess.run(
        [velo_bin, "serve", "main:app", "--log-format", "json", "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    print(f"DEBUG STDERR:\n{result.stderr}")
    found_timing = False
    for line in result.stderr.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if data.get("msg") == "Server ready":
                    assert "timing_ms" in data
                    found_timing = True
            except json.JSONDecodeError as e:
                print(f"FAILED TO DECODE: {repr(line)}")
                raise e
    assert found_timing


def test_r4_scaling_warning(tmp_path):
    # Create 5001 .py files
    for i in range(5001):
        (tmp_path / f"file_{i}.py").touch()
    (tmp_path / "main.py").write_text("app = None")

    velo_bin = get_velo_binary()

    result = subprocess.run(
        [velo_bin, "serve", "main:app", "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "warn: Large number of files detected (5002)" in result.stderr
