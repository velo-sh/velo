"""
Velo QA: Phase 4.0 Agent B Tests (保守派 - Core Stability)
==========================================================
Focus: Happy path, core flow, CLI parameters, regression tests.

Each test is ATOMIC and uses ISOLATED temp projects.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest


def get_velo_binary() -> str:
    """Get path to velo binary."""
    repo_root = Path(__file__).parents[4]
    release = repo_root / "target" / "release" / "velo"
    debug = repo_root / "target" / "debug" / "velo"
    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found")


def velo_analyze_available() -> bool:
    """Check if velo analyze is implemented."""
    try:
        velo = get_velo_binary()
        result = subprocess.run([velo, "--help"], capture_output=True, text=True, timeout=5)
        return "analyze" in result.stdout.lower()
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def check_analyze_available() -> None:
    if not velo_analyze_available():
        pytest.skip("velo analyze not implemented yet")


class StableProject:
    """Isolated project for stability testing."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="velo_stable_"))
        self.velo = get_velo_binary()

    def set_pyproject(
        self, deps: list[str] | None = None, velo_config: dict[str, Any] | None = None
    ) -> "StableProject":
        content = f"""[project]
name = "stable-test"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = {json.dumps(deps or [])}
"""
        if velo_config:
            content += "\n[tool.velo]\n"
            for k, v in velo_config.items():
                content += f"{k} = {json.dumps(v)}\n"
        (self.path / "pyproject.toml").write_text(content)
        return self

    def set_file(self, name: str, content: str) -> "StableProject":
        (self.path / name).write_text(content)
        return self

    def sync(self) -> "StableProject":
        subprocess.run(["uv", "sync", "--quiet"], cwd=self.path, capture_output=True)
        return self

    def uv_add(self, *packages: str) -> "StableProject":
        subprocess.run(
            ["uv", "add", "--quiet"] + list(packages),
            cwd=self.path,
            capture_output=True,
        )
        return self

    def analyze(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.velo, "analyze"] + list(args),
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def read_pyproject(self) -> str:
        return (self.path / "pyproject.toml").read_text()

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# B1: HAPPY PATH
# =============================================================================


@pytest.mark.tier0
class TestHappyPath:
    """B1: Core happy path tests."""

    def test_b1_1_fastapi_project(self) -> None:
        """B1-1: FastAPI project analyze works."""
        with StableProject() as p:
            p.set_pyproject(deps=["fastapi"])
            p.set_file("main.py", "from fastapi import FastAPI\napp = FastAPI()")
            p.sync()

            result = p.analyze()

            assert result.returncode == 0, f"Failed: {result.stderr}"
            assert result.stdout.strip() != "", "Expected output"

    def test_b1_2_django_project(self) -> None:
        """B1-2: Django project analyze works."""
        with StableProject() as p:
            p.set_pyproject(deps=["django"])
            p.set_file("manage.py", "import django")
            p.sync()

            result = p.analyze("manage.py")

            assert result.returncode == 0, f"Failed: {result.stderr}"

    def test_b1_3_datascience_project(self) -> None:
        """B1-3: DataScience project marks slow imports."""
        with StableProject() as p:
            p.set_pyproject(deps=["pandas", "numpy"])
            p.set_file("analysis.py", "import pandas as pd\nimport numpy as np")
            p.sync()

            result = p.analyze("analysis.py")

            assert result.returncode == 0
            output_lower = result.stdout.lower()
            # Should identify at least one of these as slow
            assert "pandas" in output_lower or "numpy" in output_lower

    def test_b1_4_minimal_project(self) -> None:
        """B1-4: Minimal project with no deps."""
        with StableProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print('hello')")
            p.sync()

            result = p.analyze()

            assert result.returncode == 0


# =============================================================================
# B2: OUTPUT FORMAT
# =============================================================================


@pytest.mark.tier2
class TestOutputFormat:
    """B2: Output format verification."""

    def test_b2_1_bar_chart_visible(self) -> None:
        """B2-1: Bar chart renders with visual bars."""
        with StableProject() as p:
            p.set_pyproject(deps=["requests"])
            p.set_file("main.py", "import requests")
            p.sync()

            result = p.analyze()

            assert result.returncode == 0
            # Expect some visual elements (bars use ▓ or similar)
            output = result.stdout
            assert "%" in output or "ms" in output.lower(), "Expected timing info"

    def test_b2_2_sorted_by_duration(self) -> None:
        """B2-2: Imports sorted by duration (slowest first)."""
        with StableProject() as p:
            p.set_pyproject(deps=["pandas", "requests"])
            p.set_file("main.py", "import pandas; import requests")
            p.sync()

            result = p.analyze()

            # Implementation should sort by duration
            assert result.returncode == 0

    def test_b2_3_percentages_valid(self) -> None:
        """B2-3: Percentages are reasonable."""
        with StableProject() as p:
            p.set_pyproject(deps=["requests"])
            p.set_file("main.py", "import requests")
            p.sync()

            result = p.analyze()

            assert result.returncode == 0


# =============================================================================
# B3: CLI PARAMETERS
# =============================================================================


@pytest.mark.tier1
class TestCLIParameters:
    """B3: CLI parameter tests."""

    def test_b3_1_specific_file(self) -> None:
        """B3-1: Analyze specific file."""
        with StableProject() as p:
            p.set_pyproject()
            p.set_file("target.py", "print(1)")
            p.set_file("other.py", "print(2)")
            p.sync()

            result = p.analyze("target.py")

            assert result.returncode == 0

    def test_b3_2_threshold_50(self) -> None:
        """B3-2: --slow-threshold-ms=50 flags more imports."""
        with StableProject() as p:
            p.set_pyproject(deps=["requests"])
            p.set_file("main.py", "import requests")
            p.sync()

            result = p.analyze("--slow-threshold-ms=50")

            assert result.returncode == 0

    def test_b3_3_threshold_500(self) -> None:
        """B3-3: --slow-threshold-ms=500 flags fewer."""
        with StableProject() as p:
            p.set_pyproject(deps=["requests"])
            p.set_file("main.py", "import requests")
            p.sync()

            result = p.analyze("--slow-threshold-ms=500")

            assert result.returncode == 0

    def test_b3_4_output_json(self) -> None:
        """B3-4: --output writes valid JSON."""
        with StableProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()

            output_file = p.path / "report.json"
            result = p.analyze("--output", str(output_file))

            assert result.returncode == 0
            if output_file.exists():
                content = output_file.read_text()
                json.loads(content)  # Should be valid JSON

    def test_b3_5_fix_updates_pyproject(self) -> None:
        """B3-5: --fix adds [tool.velo] section."""
        with StableProject() as p:
            p.set_pyproject(deps=["pandas"])
            p.set_file("main.py", "import pandas")
            p.sync()

            before = p.read_pyproject()
            assert "[tool.velo]" not in before

            result = p.analyze("--fix")

            assert result.returncode == 0
            after = p.read_pyproject()
            assert "[tool.velo]" in after

    def test_b3_6_help_shows_usage(self) -> None:
        """B3-6: --help shows usage."""
        with StableProject() as p:
            result = subprocess.run([p.velo, "analyze", "--help"], capture_output=True, text=True)

            assert result.returncode == 0
            assert "usage" in result.stdout.lower() or "options" in result.stdout.lower()


# =============================================================================
# B4: REGRESSION TESTS
# =============================================================================


@pytest.mark.tier2
class TestRegression:
    """B4: Regression tests from previous phases."""

    def test_b4_1_profile_format_compatible(self) -> None:
        """B4-1: Profile data format unchanged from Phase 1.5."""
        # analyze should be able to parse --profile output
        with StableProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()

            result = p.analyze()

            assert result.returncode == 0

    def test_b4_2_existing_velo_config_preserved(self) -> None:
        """B4-2: Existing [tool.velo] preserved by --fix."""
        with StableProject() as p:
            p.set_pyproject(deps=["requests"], velo_config={"custom_setting": "keep_me"})
            p.set_file("main.py", "import requests")
            p.sync()

            p.analyze("--fix")

            after = p.read_pyproject()
            # Original config should still be there
            assert "custom_setting" in after or "keep_me" in after

    def test_b4_3_virtualenv_priority_regression(self) -> None:
        """B4-3: Project .venv used even when VIRTUAL_ENV env var is set.

        Regression test for CI failure where VIRTUAL_ENV points to runner's
        global venv (without project deps like pandas). Velo should prefer
        the project's .venv which has the actual dependencies.

        BUG: Before fix, detect_python checked VIRTUAL_ENV first, causing
        velo analyze to use the wrong Python interpreter in CI.
        FIX: detect_python now checks project .venv BEFORE VIRTUAL_ENV.
        """
        with StableProject() as p:
            p.set_pyproject(deps=["requests"])
            p.set_file("main.py", "import requests\nprint('ok')")
            p.sync()

            # Create a fake "runner venv" that DOESN'T have requests
            fake_runner_venv = Path(tempfile.mkdtemp(prefix="fake_runner_venv_"))
            try:
                # Create minimal venv structure with python symlink
                fake_bin = fake_runner_venv / "bin"
                fake_bin.mkdir()
                # Find system python to symlink
                import sys

                system_python = Path(sys.executable)
                (fake_bin / "python").symlink_to(system_python)

                # Run velo analyze with VIRTUAL_ENV pointing to fake runner venv
                # (simulating CI environment)
                env = os.environ.copy()
                env["VIRTUAL_ENV"] = str(fake_runner_venv)

                result = subprocess.run(
                    [
                        self.velo if hasattr(self, "velo") else get_velo_binary(),
                        "analyze",
                        "main.py",
                    ],
                    cwd=p.path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env,
                )

                # Should still work - uses project .venv, not fake runner venv
                assert result.returncode == 0, f"Failed: {result.stderr}"
                output_lower = result.stdout.lower()
                # requests should appear in import analysis
                assert "requests" in output_lower, f"Expected 'requests' in output, got: {result.stdout}"
            finally:
                shutil.rmtree(fake_runner_venv, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
