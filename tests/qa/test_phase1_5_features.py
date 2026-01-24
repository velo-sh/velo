from __future__ import annotations

"""
Velo QA: Phase 1.5 Feature Tests
================================
Adversarial tests for Phase 1.5 RFC-0001 features:
- velo info command
- --profile flag

Goal: Break the new features with edge cases!
"""


from test_harness import (
    VeloTestEnv,
    assert_no_crash,
    run_velo,
)


class TestVeloInfo:
    """Tests for `velo info` command."""

    def test_info_outside_project(self):
        """velo info in directory without .venv should not crash."""
        env = VeloTestEnv()
        try:
            # No venv, no uv.lock - bare directory
            result = run_velo(["info"], cwd=env.path)
            assert_no_crash(result)
            # May show warnings but should not crash
        finally:
            env.cleanup()

    def test_info_with_corrupted_cache(self):
        """velo info with corrupted cache should show status gracefully."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            # Corrupt cache
            env.corrupt_cache("random")

            result = run_velo(["info"], cwd=env.path)
            assert_no_crash(result)
            # Should still show Hardware section
            assert "Hardware" in result.stdout or "hardware" in result.stdout.lower()
        finally:
            env.cleanup()

    def test_info_with_no_python(self):
        """velo info without Python should show error gracefully."""
        env = VeloTestEnv()
        try:
            env.create_uv_lock()
            # Create broken .venv with no executable
            venv_bin = env.venv_path / "bin"
            venv_bin.mkdir(parents=True)

            result = run_velo(["info"], cwd=env.path, env={"VELO_PYTHON": "/nonexistent"})
            assert_no_crash(result)
        finally:
            env.cleanup()

    def test_info_shows_abi_tag(self):
        """velo info should show ABI tag."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()

            result = run_velo(["info"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
            # Should contain ABI info
            assert "ABI" in result.stdout or "cpython" in result.stdout
        finally:
            env.cleanup()


class TestProfile:
    """Tests for `velo run --profile` flag."""

    def test_profile_basic(self):
        """--profile should work with simple script."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("simple.py", "print('hello')")

            result = run_velo(["run", "--profile", "simple.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
            # Should show timing info
            assert "time" in result.stdout.lower() or "profile" in result.stdout.lower()
        finally:
            env.cleanup()

    def test_profile_with_imports(self):
        """--profile should show import timing."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("imports.py", "import os\nimport sys\nprint('done')")

            result = run_velo(["run", "--profile", "imports.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()

    def test_profile_crashing_script(self):
        """--profile with crashing script should handle gracefully."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("crash.py", "raise RuntimeError('boom')") from None

            result = run_velo(["run", "--profile", "crash.py"], cwd=env.path)
            assert_no_crash(result)
            # Script fails but velo should not crash
            assert result.returncode != 0  # Script error expected
        finally:
            env.cleanup()

    def test_profile_empty_script(self):
        """--profile with empty script should work."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("empty.py", "")

            result = run_velo(["run", "--profile", "empty.py"], cwd=env.path)
            assert_no_crash(result)
            assert result.success
        finally:
            env.cleanup()

    def test_profile_with_output(self):
        """--profile should not corrupt script output."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script("output.py", "print('MARKER_12345')")

            result = run_velo(["run", "--profile", "output.py"], cwd=env.path)
            assert_no_crash(result)
            # Script output should be present
            assert "MARKER_12345" in result.stdout
        finally:
            env.cleanup()


class TestABIMismatch:
    """Tests for ABI mismatch detection."""

    def test_cache_with_different_abi(self):
        """Cache created with different ABI should trigger warning/rebuild."""
        env = VeloTestEnv()
        try:
            env.create_venv()
            env.create_uv_lock()
            env.create_script()

            # First run to create cache
            result1 = run_velo(["run", "test.py"], cwd=env.path)
            assert result1.success

            # Manually corrupt the cache to simulate ABI change
            # (since we can't easily switch Python versions in test)
            if env.cache_file.exists():
                # Modify cache content
                content = env.cache_file.read_bytes()
                # Replace cpython version in cache (simplified test)
                modified = content.replace(b"311", b"310")
                env.cache_file.write_bytes(modified)

            # Second run should handle gracefully
            result2 = run_velo(["run", "test.py"], cwd=env.path)
            assert_no_crash(result2)
            # Should succeed after rebuild
            assert result2.success
        finally:
            env.cleanup()
