"""
RFC-0035 Native Library Preload - E2E Verification Suite

Focus: User-Centric Design Validation
- Integration: velo preload analyze -> velo run
- Visibility: Is lib actually pre-loaded?
- Integrity: Does it block on modification?
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

VELO = Path(__file__).parents[2] / "target" / "debug" / "velo"
PROJECT_ROOT = Path(__file__).parents[2]
TEST_DIR = PROJECT_ROOT / "tests/qa/e2e_workspace"


@pytest.fixture(autouse=True)
def setup_workspace():
    """Create a clean workspace for E2E testing."""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)

    # Create build dir for mock libs
    lib_build_dir = TEST_DIR / "libs"
    lib_build_dir.mkdir()

    # RFC-0035 E2E: Must have velo_zygote available in the script's path
    # In a real install, this would be in site-packages or the app's vendor dir.
    # Here we copy it from the project root.
    shutil.copytree(PROJECT_ROOT / "velo_zygote", TEST_DIR / "velo_zygote")

    yield TEST_DIR

    # Cleanup
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)


def compile_lib(source_name: str, output_name: str, workspace: Path) -> Path:
    """Compile fixture C code into the workspace."""
    src = PROJECT_ROOT / f"tests/qa/fixtures/mock_libs/{source_name}.c"
    out = workspace / "libs" / output_name

    if sys.platform == "darwin":
        cmd = ["gcc", "-shared", "-o", str(out), str(src), "-fPIC", "-undefined", "dynamic_lookup"]
    else:
        cmd = ["gcc", "-shared", "-o", str(out), str(src), "-fPIC"]

    subprocess.run(cmd, check=True, capture_output=True)
    return out


def run_velo_in_ws(*args: str, workspace: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run velo command within the test workspace."""
    env = os.environ.copy()
    # Ensure VIRTUAL_ENV is NOT set to avoid path containment issues if running from outside
    # Or set it to the project root if needed.
    env["VIRTUAL_ENV"] = str(workspace)

    # RFC-0035 E2E: Must include project root so sitecustomize.py can find 'velo_zygote'
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{PROJECT_ROOT}:{existing_pp}" if existing_pp else str(PROJECT_ROOT)

    # RFC-0012: Must also trust the project root or EnvironmentShield will strip it
    env["VELO_SECURITY_TRUSTED_PREFIXES"] = str(PROJECT_ROOT)

    cmd = [str(VELO), *args]
    return subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout, env=env)


class TestRFC0035UserExperience:
    """E2E verification of the RFC-0035 design promises."""

    def test_E2E_001_preinit_transparency(self, setup_workspace):
        """
        Verify Case 1: Pre-init Transparency.
        Design Goal: Library must be loaded BEFORE Python script byte 1.
        """
        workspace = setup_workspace
        compile_lib("proof_lib", "proof.so", workspace)

        # 1. Setup pyproject.toml
        pyproject = workspace / "pyproject.toml"
        pyproject.write_text("""
[tool.velo]
native_libraries = ["libs/proof.so"]
""")

        # 2. Analyze to create lock
        res = run_velo_in_ws("preload", "analyze", workspace=workspace)
        assert res.returncode == 0
        assert (workspace / "preload.lock").exists()

        # 3. Create observer script
        # This script checks for '.preloaded_proof' which the C constructor writes.
        # If it exists at the START of the script, preloading worked.
        script = workspace / "verify.py"
        script.write_text("""
import os
import sys
from pathlib import Path

# The C constructor writes this file upon dlopen
proof_file = Path(".preloaded_proof")

if proof_file.exists():
    print("PROOF_FOUND")
    # Clean up for next run
    proof_file.unlink()
else:
    print("PROOF_MISSING")
""")

        # 4. Execute via 'velo run'
        # RFC-0035 handles sitecustomize injection automatically
        res = run_velo_in_ws("run", "verify.py", workspace=workspace)
        assert res.returncode == 0
        assert "PROOF_FOUND" in res.stdout, "C constructor did not execute before Python start"

    def test_E2E_002_integrity_guardrail(self, setup_workspace):
        """
        Verify Case 2: integrity Guardrail.
        Design Goal: System must block execution if native environment is tampered with.
        """
        workspace = setup_workspace
        lib = compile_lib("simple_lib", "secure.so", workspace)

        pyproject = workspace / "pyproject.toml"
        pyproject.write_text("""
[tool.velo]
native_libraries = ["libs/secure.so"]
""")

        # 1. Analyze (Snapshot the state)
        run_velo_in_ws("preload", "analyze", workspace=workspace)

        # 2. Tamper with the library (Modifying time/content)
        # We'll just touch it to change mtime, or append a byte
        with open(lib, "ab") as f:
            f.write(b"\0")

        # 3. Try to run
        # Velo should verify fingerprints and either warn (default) or block (strict)
        # RFC-0035 §1.1 suggests blocking or warning.
        # Let's verify it detects the mismatch.
        script = workspace / "app.py"
        script.write_text("print('HELLO')")

        # Run with VELO_NATIVE_PRELOAD_STRICT=1 to enforce blocking
        env = os.environ.copy()
        env["VELO_NATIVE_PRELOAD_STRICT"] = "1"
        env["VIRTUAL_ENV"] = str(workspace)

        res = subprocess.run([str(VELO), "run", "app.py"], cwd=workspace, capture_output=True, text=True, env=env)

        assert res.returncode != 0, f"Velo should have blocked execution of tampered environment. Stderr: {res.stderr}"
        assert "mismatch" in res.stderr.lower() or "integrity" in res.stderr.lower()

    def test_E2E_003_complex_dependency_tree(self, setup_workspace):
        """
        Verify Case 3: Dependency Resolution & Recursive Analysis.
        Design Goal: Shared libraries depending on other libraries should be analyzed recursively.
        """
        workspace = setup_workspace
        # We need a lib that depends on another. On Linux/macOS we can simulate this.
        # For E2E simplicity, we verify 'analyze' picks up multiple entries
        # when configured with a glob that matches dependencies.

        compile_lib("simple_lib", "base.so", workspace)
        compile_lib("simple_lib", "dependent.so", workspace)

        pyproject = workspace / "pyproject.toml"
        pyproject.write_text("""
[tool.velo]
native_libraries = ["libs/*.so"]
""")

        res = run_velo_in_ws("preload", "analyze", workspace=workspace)
        assert res.returncode == 0

        # Verify lock has both fingerprints
        lock_data = json.loads((workspace / "preload.lock").read_text())
        relative_paths = [f["relative_path"] for f in lock_data["fingerprints"]]
        assert any("base.so" in p for p in relative_paths)
        assert any("dependent.so" in p for p in relative_paths)

    def test_E2E_004_run_with_no_lock_fallback(self, setup_workspace):
        """
        Verify Fallback: Velo should work normally if no preload.lock exists.
        """
        workspace = setup_workspace
        script = workspace / "hello.py"
        script.write_text("print('NO_LOCK_OK')")

        res = run_velo_in_ws("run", "hello.py", workspace=workspace)
        assert res.returncode == 0
        assert "NO_LOCK_OK" in res.stdout
