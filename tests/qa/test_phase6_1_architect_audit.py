"""
Velo QA: Phase 6.1 Architectural Audit Verification
====================================================
Verifies compliance with ADR-0010-001 mandates:
- JSON logging format
- Rich error display (source-pointing)
- Security rejections (shell metacharacters)
"""

import json
import os
import subprocess
import time
from pathlib import Path
import pytest

def get_velo_binary():
    repo_root = Path(__file__).parent.parent.parent
    debug = repo_root / "target" / "debug" / "velo"
    release = repo_root / "target" / "release" / "velo"
    
    # Prioritize debug for active dev
    if debug.exists(): return str(debug)
    if release.exists(): return str(release)
    pytest.skip("velo binary not found")

@pytest.fixture
def test_env(tmp_path):
    # Setup minimal project
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\ndependencies=["fastapi", "uvicorn"]')
    (tmp_path / "uv.lock").write_text("{}")
    (tmp_path / "main.py").write_text('from fastapi import FastAPI\napp = FastAPI()')
    return tmp_path

def test_json_logging_format(test_env):
    """ADR-0010-D5: Verify JSON logging output."""
    velo = get_velo_binary()
    # Run serve with invalid port to force quick exit but after logging start
    proc = subprocess.Popen(
        [velo, "serve", "main:app", "--log-format", "json", "--port", "1"],
        cwd=test_env,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for some output or exit
    time.sleep(1)
    proc.terminate()
    _, stderr = proc.communicate()
    
    # Verify at least one line is valid JSON with mandatory keys
    json_lines = [line for line in stderr.splitlines() if line.strip().startswith('{')]
    assert len(json_lines) > 0, "No JSON logs found in stderr"
    
    log_entry = json.loads(json_lines[0])
    assert "timestamp" in log_entry
    assert "level" in log_entry
    assert "msg" in log_entry
    assert log_entry["level"] in ["info", "warn", "error"]

def test_rich_error_shell_injection(test_env):
    """SEC-P0-001: Verify rich error display for shell injection."""
    velo = get_velo_binary()
    result = subprocess.run(
        [velo, "serve", "main:app; ls"],
        cwd=test_env,
        capture_output=True,
        text=True
    )
    
    assert result.returncode != 0
    # Must contain rust-style error markers
    assert "error:" in result.stderr
    assert "-->" in result.stderr
    assert "|" in result.stderr
    assert "shell metacharacters" in result.stderr
    assert "security" in result.stderr

def test_rich_error_invalid_format(test_env):
    """D12: Verify rich error display for invalid app format."""
    velo = get_velo_binary()
    result = subprocess.run(
        [velo, "serve", "invalid_app_no_colon"],
        cwd=test_env,
        capture_output=True,
        text=True
    )
    
    assert result.returncode != 0
    assert "error:" in result.stderr
    assert "-->" in result.stderr
    assert "help:" in result.stderr
    assert "main:app" in result.stderr

def test_json_logging_contains_framework_detection(test_env):
    """Verify framework detection is logged in JSON."""
    velo = get_velo_binary()
    proc = subprocess.Popen(
        [velo, "serve", "main:app", "--log-format", "json", "--port", "19899"],
        cwd=test_env,
        stderr=subprocess.PIPE,
        text=True
    )
    
    time.sleep(1)
    proc.terminate()
    _, stderr = proc.communicate()
    
    assert "Detected: FastAPI" in stderr
    # Verify it is valid JSON
    found_detected = False
    for line in stderr.splitlines():
        if "Detected" in line:
            log_entry = json.loads(line)
            assert log_entry["level"] == "info"
            assert "FastAPI" in log_entry["msg"]
            found_detected = True
            break
    assert found_detected
