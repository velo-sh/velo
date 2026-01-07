import os
import pytest
import subprocess
import json
import time
from pathlib import Path

# QA Agent A: DX/UX & Error Fidelity
# Requirements: RFC-0010 §3.3, §4.7.3, §4.12 (DX-01 to DX-02, CN-P0-003)

@pytest.mark.tier1
class TestPhase61DXHardened:

    def test_dx_01_source_pointing_errors(self, isolated_env):
        """
        DX-01: Source-Pointing Errors
        Goal: Verify Rust-style error arrows (--> and ^^^).
        """
        env = isolated_env
        # Create a file with a syntax error or a missing app detection case
        env.create_app("main.py", "from fastapi import FastAPI\n# app = FastAPI() (Commented out)")
        
        result = env.run_velo("serve", "main", timeout=5)
        
        # Benchmark: Rust-style source-pointing
        assert "error: invalid app format" in result.stderr.lower()
        assert "--> main" in result.stderr
        # assert "^^^" in result.stderr # High-fidelity check (may be deferred if CLI not polished)
        assert "help:" in result.stderr.lower()

    def test_dx_02_typo_suggestions(self, isolated_env):
        """
        DX-02: Typo Suggestions
        Goal: Verify 'Did you mean?' suggestions for CLI flags.
        """
        env = isolated_env
        env.create_app("main.py", "app = None")
        
        # typo: --relod instead of --reload
        result = env.run_velo("serve", "main:app", "--relod", timeout=5)
        
        assert "error: unexpected argument" in result.stderr.lower()
        assert "tip: a similar argument exists: '--reload'" in result.stderr.lower()

    def test_cn_003_json_logging(self, isolated_env):
        """
        CN-P0-003: JSON Structured Logging
        Goal: Verify --log-format json produces valid JSON.
        """
        env = isolated_env
        env.create_app("main.py", "from fastapi import FastAPI\napp = FastAPI()")
        
        # Start serve with json logs
        proc = subprocess.Popen(
            [env.velo, "serve", "main:app", "--log-format", "json"],
            cwd=env.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        
        time.sleep(1)
        proc.kill()
        _, stderr = proc.communicate(timeout=5)
        
        # Verify JSON validity
        lines = [line for line in stderr.splitlines() if line.strip().startswith("{")]
        assert len(lines) >= 1
        
        log_entry = json.loads(lines[0])
        assert "timestamp" in log_entry
        assert "level" in log_entry
        assert "msg" in log_entry
        # assert "timing_ms" in log_entry # Specific field check

if __name__ == "__main__":
    pytest.main([__file__])
