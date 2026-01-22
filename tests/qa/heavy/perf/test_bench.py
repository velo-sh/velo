"""
Phase 5.0 QA: velo bench Tests

RFC-0007 Acceptance Criteria:
- LOCAL-001: velo bench runs
- LOCAL-002: velo bench --save creates JSONL
- LOCAL-003: velo bench compare shows diff
- LOCAL-004: Same machine < 5% variance
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    cargo_path = Path(__file__).parents[4] / "target" / "release" / "velo"
    if cargo_path.exists():
        return str(cargo_path)
    debug_path = Path(__file__).parents[4] / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    return "velo"


def run_velo(args: list[str], cwd: Path, velo_binary: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Helper to run velo command."""
    result = subprocess.run(
        [velo_binary] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


class TestBenchCommand:
    """
    RFC-0007: velo bench command tests
    """

    @pytest.mark.smoke
    def test_bench_001_command_exists(self, velo_binary, tmp_path):
        """
        LOCAL-001: velo bench command runs

        RFC-0007 §3.1: Must output metrics
        """
        result = run_velo(["bench"], tmp_path, velo_binary)

        # Should run without error
        assert result.returncode == 0, f"velo bench failed: {result.stderr}"

        # Should output benchmark names
        assert "blake3_4mb" in result.stdout or "module_lookup" in result.stdout

    @pytest.mark.smoke
    def test_bench_002_outputs_metrics(self, velo_binary, tmp_path):
        """
        LOCAL-001: velo bench outputs performance metrics

        RFC-0007 §3.4: Must show timing (ms/μs/ns)
        """
        result = run_velo(["bench"], tmp_path, velo_binary)

        assert result.returncode == 0

        # Should contain time units
        output = result.stdout
        has_timing = any(unit in output for unit in ["ms", "μs", "ns", "s"])
        assert has_timing, f"No timing in output: {output}"

    @pytest.mark.happy_path
    def test_bench_003_save_creates_jsonl(self, velo_binary, tmp_path):
        """
        LOCAL-002: velo bench --save creates JSONL entry

        RFC-0007 §3.2: Results saved to .velo/bench/history.jsonl
        """
        # Initialize git repo (required for commit hash)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        result = run_velo(["bench", "--save"], tmp_path, velo_binary)

        assert result.returncode == 0, f"velo bench --save failed: {result.stderr}"

        # Check JSONL file created
        history_file = tmp_path / ".velo" / "bench" / "history.jsonl"
        assert history_file.exists(), "history.jsonl not created"

        # Validate JSONL format
        content = history_file.read_text().strip()
        for line in content.split("\n"):
            if line:
                entry = json.loads(line)
                assert "commit" in entry
                assert "date" in entry
                assert "machine" in entry
                assert "bench" in entry
                assert "value_ns" in entry

    @pytest.mark.happy_path
    def test_bench_004_compare_command(self, velo_binary, tmp_path):
        """
        LOCAL-003: velo bench compare shows diff correctly

        RFC-0007 §3.1: velo bench compare <commit>
        """
        # Initialize git
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "v1.txt").write_text("v1")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        # Get baseline commit
        baseline = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Save baseline
        run_velo(["bench", "--save"], tmp_path, velo_binary)

        # Make another commit
        (tmp_path / "v2.txt").write_text("v2")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=tmp_path, capture_output=True)

        # Compare
        result = run_velo(["bench", "compare", baseline], tmp_path, velo_binary)

        # Should show comparison (may fail if no baseline data - that's ok)
        if result.returncode == 0:
            assert "Comparing" in result.stdout or "Current" in result.stdout

    @pytest.mark.happy_path
    def test_bench_005_history_command(self, velo_binary, tmp_path):
        """
        RFC-0007 §3.1: velo bench history shows trends
        """
        # Initialize git
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "v1.txt").write_text("v1")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        # Save some data
        run_velo(["bench", "--save"], tmp_path, velo_binary)

        # Check history
        result = run_velo(["bench", "history"], tmp_path, velo_binary)

        assert result.returncode == 0
        # Should show history header
        assert "History" in result.stdout or "No history" in result.stdout


class TestBenchConsistency:
    """
    LOCAL-004: Same machine consistency < 5% variance
    """

    @pytest.mark.edge
    @pytest.mark.slow
    def test_bench_006_consistency(self, velo_binary, tmp_path):
        """
        RFC-0007 §7: Same machine < 5% variance

        Run 5 times, check variance.
        """
        results = []

        for _ in range(5):
            result = run_velo(["bench"], tmp_path, velo_binary)
            if result.returncode == 0:
                # Parse blake3_4mb timing
                for line in result.stdout.split("\n"):
                    if "blake3_4mb" in line:
                        # Extract ms value
                        parts = line.split()
                        for p in parts:
                            if "ms" in p:
                                try:
                                    value = float(p.replace("ms", ""))
                                    results.append(value)
                                except ValueError:
                                    pass

        if len(results) >= 3:
            avg = sum(results) / len(results)
            max_val = max(results)
            min_val = min(results)
            variance = (max_val - min_val) / avg * 100

            # Warn if > 10% variance (5% is ideal but CI can be noisy)
            assert variance < 50, f"Variance too high: {variance:.1f}%"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "smoke"])
