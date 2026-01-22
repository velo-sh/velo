"""
Phase 5.0 Fast Loader: pytest configuration

Provides fixtures and markers for L0-L5 tests.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Add python/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python"))


# === Pytest Markers ===


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "smoke: L0 Smoke tests (always run)")
    config.addinivalue_line("markers", "happy_path: L1 Happy Path tests")
    config.addinivalue_line("markers", "sad_path: L2 Sad Path tests")
    config.addinivalue_line("markers", "config: L3 Configuration tests")
    config.addinivalue_line("markers", "security: L4 Security tests")
    config.addinivalue_line("markers", "edge: L5 Edge/Chaos tests")
    config.addinivalue_line("markers", "slow: Tests that take > 10 seconds")


# === Shared Fixtures ===


@pytest.fixture(scope="session")
def velo_binary():
    """
    Get path to velo binary.

    Searches in order:
    1. VELO_BINARY environment variable
    2. Release build in workspace
    3. Debug build in workspace
    4. System PATH
    """
    # Check environment variable
    if "VELO_BINARY" in os.environ:
        return os.environ["VELO_BINARY"]

    # Find workspace root
    workspace_root = Path(__file__).parent.parent.parent.parent

    # Try release build
    release_path = workspace_root / "target" / "release" / "velo"
    if release_path.exists():
        return str(release_path)

    # Try debug build
    debug_path = workspace_root / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)

    # Assume in PATH
    return "velo"


@pytest.fixture
def simple_project():
    """
    Create minimal Python project for testing.

    Structure:
        project_dir/
        ├── main.py          (prints "Hello from Fast Loader!")
        └── pyproject.toml

    Note: Uses workspace-local directory instead of /tmp to avoid
    Velo's InsecureLocation security check (bundle caching rejects
    shared directories like /tmp).
    """
    import shutil
    import uuid

    # Use workspace-local test directory to avoid InsecureLocation errors
    workspace_root = Path(__file__).parent.parent.parent.parent
    local_test_dir = workspace_root / ".test_projects"
    local_test_dir.mkdir(exist_ok=True)

    project_dir = local_test_dir / f"proj_{uuid.uuid4().hex}"
    project_dir.mkdir()

    main_py = project_dir / "main.py"
    main_py.write_text(
        """
import json
print("Hello from Fast Loader!")
data = json.dumps({"status": "ok"})
print(data)
"""
    )

    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "test-project"
version = "0.1.0"
requires-python = ">=3.11"
"""
    )

    yield project_dir

    # Cleanup
    if project_dir.exists():
        shutil.rmtree(project_dir)


@pytest.fixture
def run_velo(velo_binary):
    """
    Factory fixture to run velo commands.

    Usage:
        def test_example(run_velo, simple_project):
            result = run_velo(["build"], simple_project)
            assert result.returncode == 0
    """

    def _run(args: list, cwd: Path, timeout: int = 60, env=None):
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        result = subprocess.run(
            [velo_binary] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )
        return result

    return _run


@pytest.fixture
def build_bundle():
    """
    Fixture to build bundle using Python builder.

    Usage:
        def test_example(build_bundle, simple_project):
            bundle_path = build_bundle(simple_project)
            assert bundle_path.exists()
    """
    from bundle_builder import build_from_project

    def _build(project_dir: Path, output_path: Path = None) -> Path:
        if output_path is None:
            cache_dir = project_dir / ".velo" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            output_path = cache_dir / "bundle.veloc"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        return build_from_project(project_dir, output_path)

    return _build


# === Test Collection Hooks ===


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection based on markers.

    Enforces test hierarchy:
    - L0 (smoke) runs first
    - L1-L5 run in order
    """
    # Sort tests by level
    level_order = {
        "smoke": 0,
        "happy_path": 1,
        "sad_path": 2,
        "config": 3,
        "security": 4,
        "edge": 5,
    }

    def get_level(item):
        for marker in item.iter_markers():
            if marker.name in level_order:
                return level_order[marker.name]
        return 99  # Unknown markers run last

    items.sort(key=get_level)


# === Skip Conditions ===


@pytest.fixture
def skip_if_no_velo(velo_binary):
    """Skip test if velo binary not available."""
    result = subprocess.run(
        [velo_binary, "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("velo binary not available")
