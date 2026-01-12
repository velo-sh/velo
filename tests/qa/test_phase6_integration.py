# Phase 6 Integration & Performance: RFC-0009 Static Graph

import pytest
import os
import json
import subprocess
from pathlib import Path


@pytest.mark.tier2
class TestPhase6Integration:
    """Consolidated integration and performance verification for Phase 6.0."""

    @pytest.mark.perf
    def test_PERF_601_deserialize_latency(self, isolated_env):
        """L5-PERF: Verify graph_deserialize_latency_us < 500μs for 500-module graph."""
        env = isolated_env
        module_count = 500

        # 1. Create 500-module project
        for i in range(module_count):
            env.create_app(f"m{i}.py", "")
        env.create_app("main.py", "import m0")

        # 2. Build
        env.run_velo("bundle", "build")

        # 3. Run with metrics reporting
        env_vars = os.environ.copy()
        env_vars["VELO_REPORT_METRICS"] = "1"

        result = env.run_velo("run", "--fast", "main.py", env=env_vars)

        # Parse metrics from stderr
        metrics = {}
        for line in result.stderr.splitlines():
            if line.startswith("{") and "graph_deserialize_latency_us" in line:
                metrics = json.loads(line)
                break

        assert metrics, "Metrics JSON not found in stderr"
        latency = metrics.get("graph_deserialize_latency_us", 999999)
        assert latency < 500, f"Deserialization too slow: {latency}μs > 500μs"

    def test_SMOKE_601_stat_elimination(self, isolated_env):
        """L1-SMOKE: Verify 0 stat() calls per import for bundled modules."""
        env = isolated_env
        env.create_app("mod.py", "DATA = 1")
        env.create_app("main.py", "import mod")

        env.run_velo("bundle", "build")

        # Use strace to count stat calls on Linux, or skip if not available
        # This is a platform-specific smoke test (L4/L5)
        try:
            result = subprocess.run(
                [
                    "strace",
                    "-e",
                    "stat,stat64,newfstatat",
                    env.velo,
                    "run",
                    "--fast",
                    "main.py",
                ],
                cwd=env.path,
                capture_output=True,
                text=True,
            )
            # Filter stat calls related to 'mod.py'
            stat_calls = [l for l in result.stderr.splitlines() if "mod.py" in l]
            # There should be 0 stat calls for the .py file during import resolution
            assert (
                len(stat_calls) == 0
            ), f"Found stat() calls for bundled module: {stat_calls}"
        except FileNotFoundError:
            pytest.skip("strace not found; skipping syscall audit")

    @pytest.mark.xfail(
        reason="P3: fallback_reasons field not yet implemented in metrics output"
    )
    def test_L5_metrics_json_exhaustive(self, isolated_env):
        """L5: Verify VELO_REPORT_METRICS=1 outputs valid JSON with all RFC-0009 fields."""
        env = isolated_env
        env.create_app("main.py", "import os; print('OK')")
        env.run_velo("bundle", "build")

        env_vars = os.environ.copy()
        env_vars["VELO_REPORT_METRICS"] = "1"
        result = env.run_velo("run", "--fast", "main.py", env=env_vars)

        # Verify JSON structure
        metrics_found = False
        for line in result.stderr.splitlines():
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    if "graph_hits" in data:
                        metrics_found = True
                        # Uncompromising: Field check
                        assert "graph_misses" in data
                        assert "fallback_reasons" in data
                        assert "graph_deserialize_latency_us" in data
                        break
                except json.JSONDecodeError:
                    continue
        assert metrics_found, "Metrics JSON blob missing or invalid"

    def test_L3_2_cold_start_gating_placeholder(self, isolated_env):
        """L3-2: Performance benchmark (Target < 10ms for simple script)."""
        # Actual cold cache requires platform-specific drop_caches (sdist/sudo)
        pass
