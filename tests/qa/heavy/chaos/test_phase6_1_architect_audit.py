"""
Velo QA: Phase 6.1 Architectural Audit Verification
====================================================
Verifies compliance with ADR-0010-001 mandates:
- JSON logging format
- Rich error display (source-pointing)
- Security rejections (shell metacharacters)
"""

import json
import subprocess
import time

import pytest
from conftest_utils import get_velo_binary


@pytest.fixture
def test_env(tmp_path):
    # Setup minimal project
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\ndependencies=["fastapi", "uvicorn"]')
    (tmp_path / "uv.lock").write_text("{}")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
    return tmp_path


def test_json_logging_format(test_env):
    """ADR-0010-D5: Verify JSON logging output."""
    velo = get_velo_binary()
    # Run serve with invalid port to force quick exit but after logging start
    proc = subprocess.Popen(
        [velo, "serve", "main:app", "--log-format", "json", "--port", "1"],
        cwd=test_env,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for some output or exit
    time.sleep(1)
    proc.terminate()
    _, stderr = proc.communicate()

    # Verify at least one line is valid JSON with mandatory keys
    json_lines = [line for line in stderr.splitlines() if line.strip().startswith("{")]
    assert len(json_lines) > 0, "No JSON logs found in stderr"

    log_entry = json.loads(json_lines[0])
    assert "timestamp" in log_entry
    assert "level" in log_entry
    assert "msg" in log_entry
    assert log_entry["level"] in ["info", "warn", "error"]


def test_rich_error_shell_injection(test_env):
    """SEC-P0-001: Verify rich error display for shell injection."""
    velo = get_velo_binary()
    result = subprocess.run([velo, "serve", "main:app; ls"], cwd=test_env, capture_output=True, text=True)

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
        text=True,
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
        text=True,
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
    assert proc.returncode is not None


def test_zero_config_discovery(test_env):
    """DX-P0-002: Verify zero-config auto-discovery."""
    velo = get_velo_binary()
    result = subprocess.run([velo, "serve", "--dry-run"], cwd=test_env, capture_output=True, text=True)

    print(result.stderr)
    assert result.returncode == 0
    assert "✨ Detected app: main:app" in result.stderr
    assert "Dry run: Command" in result.stderr


def test_dry_run_semantics(test_env):
    """PERF-P0-001: Verify dry-run exit semantics and command logging."""
    velo = get_velo_binary()
    result = subprocess.run(
        [velo, "serve", "main:app", "--dry-run"],
        cwd=test_env,
        capture_output=True,
        text=True,
    )

    print(result.stderr)
    assert result.returncode == 0
    assert "info: Starting server..." in result.stderr
    assert "Dry run: Command would be:" in result.stderr
    # On dry run, we might not always see Zygote shutdown if it's very fast,
    # let's just check it doesn't fail.


def test_typo_suggestion_tip(test_env):
    """DX-P0-002: Verify typo suggestions (Levenshtein)."""
    velo = get_velo_binary()
    result = subprocess.run(
        [velo, "serve", "main:ap", "--dry-run"],
        cwd=test_env,
        capture_output=True,
        text=True,
    )

    print(result.stderr)
    assert "tip:" in result.stderr
    assert "a similar app exists: main:app" in result.stderr


def test_path_traversal_rejection(test_env):
    """SEC-P0-002: Verify path traversal protection."""
    velo = get_velo_binary()
    # Try using an absolute path outside project root
    result = subprocess.run(
        [velo, "serve", "main:app", "--pid-file", "/tmp/velo.pid", "--dry-run"],
        cwd=test_env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Path traversal detected" in result.stderr
    assert "/tmp/velo.pid" in result.stderr


def test_path_traversal_relative_rejection(test_env):
    """SEC-P0-002: Verify relative path traversal protection (..)."""
    velo = get_velo_binary()
    # Try using '..' to escape
    result = subprocess.run(
        [velo, "serve", "main:app", "--pid-file", "../outside.pid", "--dry-run"],
        cwd=test_env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Path traversal detected" in result.stderr
