import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def get_velo_binary():
    repo_root = Path(__file__).parents[4]
    debug = repo_root / "target" / "debug" / "velo"
    release = repo_root / "target" / "release" / "velo"
    if debug.exists():
        return str(debug)
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


def setup_test_project(tmp_path):
    repo_root = Path(__file__).parents[4]
    python_src = repo_root / "python"
    python_dst = tmp_path / "python"

    # Copy detect_app.py and other helpers
    if python_src.exists():
        if python_dst.exists():
            shutil.rmtree(python_dst)
        shutil.copytree(python_src, python_dst)


def test_h1_h2_venv_discovery(tmp_path):
    """Verify detection of various venv names and dynamic site-packages."""
    velo = get_velo_binary()
    setup_test_project(tmp_path)

    # Test venv/ directory instead of .venv/
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    bin_dir = venv_dir / "bin" if os.name != "nt" else venv_dir / "Scripts"
    bin_dir.mkdir()
    python_name = "python" if os.name != "nt" else "python.exe"
    python_exe = bin_dir / python_name

    # Create a real-ish python script that reports its path
    if os.name != "nt":
        python_exe.write_text("#!/bin/sh\necho 'mock python'\n")
        python_exe.chmod(0o755)
    else:
        python_exe.touch()

    # Create a fake site-packages inside venv/lib/python3.10/site-packages
    site_pkgs = venv_dir / "lib" / "python3.10" / "site-packages"
    site_pkgs.mkdir(parents=True)

    # Run velo info - it should pick up this venv
    result = subprocess.run(
        [velo, "info"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "VIRTUAL_ENV": ""},
    )

    # Check that venv/bin/python is in the output
    assert "venv" in result.stdout


def test_h3_django_recursive(tmp_path):
    """Verify recursive Django settings detection (depth 2)."""
    velo = get_velo_binary()
    setup_test_project(tmp_path)

    # Create project/src/django_proj/settings.py
    src = tmp_path / "src"
    myproj = src / "django_proj"
    myproj.mkdir(parents=True)
    (myproj / "__init__.py").touch()
    (myproj / "settings.py").write_text("DEBUG = True")

    # Use real python for test
    env = {**os.environ, "VELO_PYTHON": sys.executable}

    # Use 'django' in app name to trigger framework detection
    result = subprocess.run(
        [velo, "serve", "src.django_proj.main:app", "--dry-run", "--host", "127.0.0.1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    # Verify inference log
    assert (
        "Inferred DJANGO_SETTINGS_MODULE=django_proj.settings" in result.stdout
        or "Inferred DJANGO_SETTINGS_MODULE=django_proj.settings" in result.stderr
    )


def test_h4_cli_command_typo():
    """Verify top-level CLI command suggestions (Levenshtein <= 2)."""
    velo = get_velo_binary()

    # Distance 1: serxe -> serve
    result = subprocess.run([velo, "serxe"], capture_output=True, text=True)
    assert "did you mean 'serve'?" in result.stderr

    # Distance 2: srv -> serve
    result = subprocess.run([velo, "srv"], capture_output=True, text=True)
    assert "did you mean 'serve'?" in result.stderr

    # Distance 3: s (too far)
    result = subprocess.run([velo, "s"], capture_output=True, text=True)
    assert "did you mean" not in result.stderr


def test_h5_app_typo_threshold(tmp_path):
    """Verify app typo suggestion threshold (mandate <= 2)."""
    velo = get_velo_binary()
    setup_test_project(tmp_path)

    # Create a real app in the root so detect_app finds it
    app_file = tmp_path / "main.py"
    app_file.write_text("from fastapi import FastAPI\napp = FastAPI()")

    # Use real python to ensure detect_app.py runs
    env = {**os.environ, "VELO_PYTHON": sys.executable}

    # Distance 1: main:apz -> main:app
    result = subprocess.run(
        [velo, "serve", "main:apz", "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "a similar app exists: main:app" in result.stderr

    # Distance 3: main:axxx -> main:app (should be ignored)
    result = subprocess.run(
        [velo, "serve", "main:axxx", "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "a similar app exists" not in result.stderr
