"""
QA: Zygote Module Acceleration Verification (RFC-0030)

Verifies that Python modules can be accelerated via the Zygote.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    # Look for binary in target/release or target/debug
    root = Path(__file__).parent.parent.parent.parent
    release_path = root / "target" / "release" / "velo"
    if release_path.exists():
        return str(release_path)
    debug_path = root / "target" / "debug" / "velo"
    if debug_path.exists():
        return str(debug_path)
    return "velo"


def run_velo(args: list, cwd: Path, velo_binary: str, env: dict = None):
    """Helper to run velo command."""
    current_env = os.environ.copy()
    if env:
        current_env.update(env)

    result = subprocess.run([velo_binary] + args, cwd=cwd, capture_output=True, text=True, env=current_env)
    return result


def stop_zygote(velo_binary: str, cwd: Path):
    """Stop any running Zygote daemon."""
    run_velo(["zygote", "stop"], cwd, velo_binary)
    time.sleep(0.5)


class TestZygoteModuleAcceleration:
    """
    Verifies RFC-0030 alignment for Zygote-accelerated module execution.
    """

    def test_module_acceleration_basic(self, velo_binary, tmp_path):
        """
        Verify that --zygote works for -m module execution.
        """
        # 1. Create a dummy module
        module_dir = tmp_path / "my_test_module"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "__main__.py").write_text(
            """
import sys
import os
print("MODULE_ACCEL_TEST_OK")
print(f"ARGV: {sys.argv}")
print(f"VELO_IS_ZYGOTE: {os.environ.get('VELO_IS_ZYGOTE')}")
"""
        )

        # Update PYTHONPATH to include the tmp_path so it can find my_test_module
        env = {"PYTHONPATH": str(tmp_path)}

        # Stop existing Zygote
        stop_zygote(velo_binary, tmp_path)

        try:
            # 2. Baseline: Run without --zygote
            # Use -- to ensure hello world are passed as args to the module
            result_native = run_velo(
                ["run", "-m", "my_test_module", "--", "hello", "world"], tmp_path, velo_binary, env=env
            )
            assert result_native.returncode == 0, f"Native run failed: {result_native.stderr}"
            assert "MODULE_ACCEL_TEST_OK" in result_native.stdout
            assert "'hello', 'world']" in result_native.stdout
            # Native run should NOT have VELO_IS_ZYGOTE
            assert "VELO_IS_ZYGOTE: None" in result_native.stdout

            # 3. Start Zygote
            start_res = run_velo(["zygote", "start"], tmp_path, velo_binary, env=env)
            assert start_res.returncode == 0, f"Zygote start failed: {start_res.stderr}"
            time.sleep(1)

            # 4. Accelerated Run
            result_zygote = run_velo(
                ["run", "--zygote", "-m", "my_test_module", "--", "foo", "bar"], tmp_path, velo_binary, env=env
            )
            assert result_zygote.returncode == 0, f"Zygote run failed: {result_zygote.stderr}"
            assert "MODULE_ACCEL_TEST_OK" in result_zygote.stdout
            assert "'foo', 'bar']" in result_zygote.stdout

            # CRITICAL: Verify it actually used the Zygote
            assert "VELO_IS_ZYGOTE: 1" in result_zygote.stdout
            assert "🚀 Accelerating module my_test_module via Iron Zygote..." in result_zygote.stderr

        finally:
            stop_zygote(velo_binary, tmp_path)

    def test_module_acceleration_complex_args(self, velo_binary, tmp_path):
        """
        Verify that complex arguments are passed correctly to the module.
        """
        # 1. Create a dummy module
        module_dir = tmp_path / "arg_test_module"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "__main__.py").write_text(
            """
import sys
print(f"COUNT: {len(sys.argv)}")
for i, arg in enumerate(sys.argv):
    print(f"ARG_{i}: {arg}")
"""
        )

        env = {"PYTHONPATH": str(tmp_path)}
        stop_zygote(velo_binary, tmp_path)

        try:
            run_velo(["zygote", "start"], tmp_path, velo_binary, env=env)
            time.sleep(1)

            # Pass some complex args
            args = ["--flag", "value", "-f", "{connection_file}", "--", "trailing"]
            result = run_velo(["run", "--zygote", "-m", "arg_test_module", "--"] + args, tmp_path, velo_binary, env=env)

            assert result.returncode == 0
            # ARGV[0] + 6 args = 7
            assert "COUNT: 7" in result.stdout
            assert "ARG_1: --flag" in result.stdout
            assert "ARG_2: value" in result.stdout
            assert "ARG_3: -f" in result.stdout
            assert "ARG_4: {connection_file}" in result.stdout
            assert "ARG_5: --" in result.stdout
            assert "ARG_6: trailing" in result.stdout

        finally:
            stop_zygote(velo_binary, tmp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
