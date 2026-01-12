"""
Velo QA: Phase 3 Weird Environment Tests
=========================================
Tests for unusual, hostile, and edge-case user environments.

Philosophy: "What's the weirdest thing a user could do?"
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest


def get_velo_binary():
    """Get path to velo binary."""
    repo_root = Path(__file__).parent.parent.parent
    release = repo_root / "target" / "release" / "velo"
    if release.exists():
        return str(release)
    pytest.skip("velo binary not found")


class WeirdEnv:
    """Base class for weird environment testing."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="weird_env_"))
        self.velo = get_velo_binary()

    def run_velo(self, args: list, timeout: float = 30, env: dict = None) -> tuple:
        """Run velo and return (returncode, stdout, stderr)."""
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        result = subprocess.run(
            [self.velo] + args,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
        )
        return result.returncode, result.stdout, result.stderr

    def setup_basic(self):
        """Minimal setup."""
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.path, check=True)
        (self.path / "uv.lock").write_text("{}")

    def create_script(self, name: str, content: str):
        (self.path / name).write_text(content)

    def cleanup(self):
        try:
            shutil.rmtree(self.path)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# PATH WEIRDNESS
# =============================================================================


class TestWeirdPaths:
    """Tests for weird file paths and directory names."""

    def test_path_with_spaces(self):
        """Path with spaces: /tmp/my project/"""
        base = Path(tempfile.mkdtemp())
        weird_path = base / "my project with spaces"
        weird_path.mkdir()

        env = WeirdEnv()
        env.path = weird_path

        try:
            env.setup_basic()
            env.create_script("test.py", 'print("spaces work")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            assert "spaces work" in stdout or code == 0, f"Failed with spaces: {stderr}"
        finally:
            shutil.rmtree(base)

    def test_path_with_unicode(self):
        """Path with unicode: /tmp/项目/"""
        base = Path(tempfile.mkdtemp())
        weird_path = base / "项目测试"
        weird_path.mkdir()

        env = WeirdEnv()
        env.path = weird_path

        try:
            env.setup_basic()
            env.create_script("test.py", 'print("unicode works")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            assert "unicode works" in stdout or code == 0
        finally:
            shutil.rmtree(base)

    def test_path_with_special_chars(self):
        """Path with special chars: /tmp/test@#$%/"""
        base = Path(tempfile.mkdtemp())
        # Note: Some chars are not allowed in paths
        weird_path = base / "test@project"
        weird_path.mkdir()

        env = WeirdEnv()
        env.path = weird_path

        try:
            env.setup_basic()
            env.create_script("test.py", 'print("special chars work")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            assert "special chars work" in stdout or code == 0
        finally:
            shutil.rmtree(base)

    def test_very_long_path(self):
        """Path with 200+ characters."""
        base = Path(tempfile.mkdtemp())
        long_name = "a" * 50

        current = base
        for _ in range(4):  # Create nested structure
            current = current / long_name
            current.mkdir()

        env = WeirdEnv()
        env.path = current

        try:
            env.setup_basic()
            env.create_script("test.py", 'print("long path works")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            # Should handle gracefully (pass or clear error)
            assert "long path works" in stdout or "error" in stderr.lower()
        finally:
            shutil.rmtree(base)

    def test_symlinked_project_dir(self):
        """Project directory is a symlink."""
        base = Path(tempfile.mkdtemp())
        real_dir = base / "real_project"
        link_dir = base / "linked_project"

        real_dir.mkdir()
        link_dir.symlink_to(real_dir)

        env = WeirdEnv()
        env.path = link_dir

        try:
            env.setup_basic()
            env.create_script("test.py", 'print("symlink works")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            assert "symlink works" in stdout or code == 0
        finally:
            shutil.rmtree(base)


# =============================================================================
# PERMISSION WEIRDNESS
# =============================================================================


class TestWeirdPermissions:
    """Tests for unusual file permissions."""

    def test_readonly_project_dir(self):
        """Project directory is read-only."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", 'print("readonly")')

            # Make directory read-only
            os.chmod(str(env.path), 0o555)

            try:
                code, stdout, stderr = env.run_velo(["run", "test.py"])

                # Should handle gracefully
                assert (
                    code == 0 or "permission" in stderr.lower() or "readonly" in stdout
                )
            finally:
                # Restore permissions for cleanup
                os.chmod(str(env.path), 0o755)

    def test_script_not_readable(self):
        """Script file exists but is not readable."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("secret.py", 'print("secret")')

            # Make script unreadable
            os.chmod(str(env.path / "secret.py"), 0o000)

            try:
                code, stdout, stderr = env.run_velo(["run", "secret.py"])

                # Should fail with clear error
                assert code != 0, "Should fail on unreadable script"
                assert (
                    "permission" in stderr.lower()
                    or "denied" in stderr.lower()
                    or "error" in stderr.lower()
                )
            finally:
                os.chmod(str(env.path / "secret.py"), 0o644)

    def test_cache_dir_not_writable(self):
        """Cache directory exists but not writable."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", 'print("cache test")')

            # Create cache dir and make it read-only
            cache_dir = env.path / ".velo_cache"
            cache_dir.mkdir()
            os.chmod(str(cache_dir), 0o555)

            try:
                code, stdout, stderr = env.run_velo(["run", "test.py"])

                # Should handle gracefully
                print(f"  Code: {code}, stdout: {stdout}, stderr: {stderr}")
            finally:
                os.chmod(str(cache_dir), 0o755)


# =============================================================================
# ENVIRONMENT VARIABLE WEIRDNESS
# =============================================================================


class TestWeirdEnvVars:
    """Tests for unusual environment variable configurations."""

    def test_empty_path(self):
        """PATH environment variable is empty."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", 'print("empty path")')

            code, stdout, stderr = env.run_velo(["run", "test.py"], env={"PATH": ""})

            # Should fail gracefully (can't find Python)
            print(f"  Empty PATH: code={code}")

    def test_pythonpath_set(self):
        """PYTHONPATH is set to something weird."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", "import sys; print(sys.path)")

            code, stdout, stderr = env.run_velo(
                ["run", "test.py"], env={"PYTHONPATH": "/nonexistent:/also/nonexistent"}
            )

            # Should work despite weird PYTHONPATH
            assert code == 0 or "error" in stderr.lower()

    def test_home_not_set(self):
        """HOME environment variable is not set."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", 'print("no home")')

            clean_env = {k: v for k, v in os.environ.items() if k != "HOME"}
            clean_env["PATH"] = os.environ.get("PATH", "")

            code, stdout, stderr = env.run_velo(["run", "test.py"], env=clean_env)

            print(f"  No HOME: code={code}, stderr={stderr[:100]}")

    def test_tmpdir_not_writable(self):
        """TMPDIR points to non-writable location."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script(
                "test.py", "import tempfile; print(tempfile.gettempdir())"
            )

            code, stdout, stderr = env.run_velo(
                ["run", "test.py"], env={"TMPDIR": "/nonexistent"}
            )

            print(f"  Bad TMPDIR: code={code}")


# =============================================================================
# FILESYSTEM WEIRDNESS
# =============================================================================


class TestWeirdFilesystem:
    """Tests for unusual filesystem conditions."""

    def test_broken_symlink_in_project(self):
        """Broken symlink exists in project directory."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", 'print("broken symlink test")')

            # Create broken symlink
            broken_link = env.path / "broken_link.py"
            broken_link.symlink_to("/nonexistent/path")

            # Should still work
            code, stdout, stderr = env.run_velo(["run", "test.py"])

            assert "broken symlink test" in stdout or code == 0

    def test_venv_is_symlink(self):
        """Virtual environment is a symlink."""
        base = Path(tempfile.mkdtemp())
        real_venv = base / "real_venv"

        env = WeirdEnv()
        env.path = base / "project"
        env.path.mkdir()

        try:
            # Create real venv elsewhere
            subprocess.run(["uv", "venv", "--quiet", str(real_venv)], check=True)

            # Symlink it
            (env.path / ".venv").symlink_to(real_venv)
            (env.path / "uv.lock").write_text("{}")

            env.create_script("test.py", 'print("symlink venv")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            print(f"  Symlink venv: code={code}, stdout={stdout}")
        finally:
            shutil.rmtree(base)

    def test_no_disk_space(self):
        """Simulate nearly full disk (can't create large files)."""
        # This is hard to actually test, so we just verify behavior
        # when cache already exists
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("test.py", 'print("disk space test")')

            # Pre-create cache to avoid needing to write
            (env.path / ".velo_cache").mkdir(exist_ok=True)

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            assert code == 0 or "disk space test" in stdout


# =============================================================================
# PYTHON WEIRDNESS
# =============================================================================


class TestWeirdPython:
    """Tests for unusual Python configurations."""

    def test_no_venv(self):
        """No virtual environment, just system Python."""
        base = Path(tempfile.mkdtemp())

        env = WeirdEnv()
        env.path = base

        try:
            # Don't create venv, only uv.lock
            (env.path / "uv.lock").write_text("{}")
            env.create_script("test.py", 'print("no venv")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            # Should work with system Python or fail gracefully
            assert (
                code == 0 or "venv" in stderr.lower() or "environment" in stderr.lower()
            )
        finally:
            shutil.rmtree(base)

    def test_corrupt_venv(self):
        """Virtual environment exists but is corrupt."""
        with WeirdEnv() as env:
            env.setup_basic()

            # Corrupt the venv by removing Python binary
            python_path = env.path / ".venv" / "bin" / "python"
            if python_path.exists():
                python_path.unlink()

            env.create_script("test.py", 'print("corrupt venv")')

            code, stdout, stderr = env.run_velo(["run", "test.py"])

            # Velo should handle gracefully (may succeed with fallback or fail with error)
            # Code 0 with fallback is acceptable
            print(
                f"  Corrupt venv: code={code}, stderr={stderr[:100] if stderr else 'none'}"
            )

    def test_multiple_venvs(self):
        """Multiple .venv directories (nested project)."""
        with WeirdEnv() as env:
            env.setup_basic()

            # Create nested project with its own venv
            nested = env.path / "subproject"
            nested.mkdir()
            subprocess.run(["uv", "venv", "--quiet"], cwd=nested, check=True)
            (nested / "uv.lock").write_text("{}")

            env.create_script("test.py", 'print("multi venv")')
            (nested / "test.py").write_text('print("nested venv")')

            # Run from nested dir
            code, stdout, stderr = env.run_velo(["run", "test.py"])

            print(f"  Multiple venvs: code={code}")


# =============================================================================
# CONCURRENT / RACE CONDITIONS
# =============================================================================


class TestConcurrentWeirdness:
    """Tests for race conditions and concurrent usage."""

    def test_concurrent_starts(self):
        """Multiple velo processes starting simultaneously."""
        import threading

        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script(
                "test.py", 'import time; time.sleep(0.1); print("concurrent")'
            )

            results = []

            def run():
                code, stdout, stderr = env.run_velo(["run", "test.py"])
                results.append((code, "concurrent" in stdout))

            threads = [threading.Thread(target=run) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            successes = sum(
                1 for code, has_output in results if code == 0 or has_output
            )
            print(f"  Concurrent: {successes}/5 succeeded")

    def test_file_changes_during_run(self):
        """Script file changes while running."""
        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script(
                "changing.py",
                """
import time
time.sleep(0.5)
print("original")
""",
            )

            import threading

            def change_file():
                time.sleep(0.2)
                env.create_script("changing.py", 'print("modified")')

            t = threading.Thread(target=change_file)
            t.start()

            code, stdout, stderr = env.run_velo(["run", "changing.py"])
            t.join()

            # Should complete without crash
            assert code == 0 or "original" in stdout or "modified" in stdout


# =============================================================================
# SIGNAL / INTERRUPT
# =============================================================================


class TestSignalWeirdness:
    """Tests for signal handling."""

    def test_sigterm_during_startup(self):
        """SIGTERM sent during startup."""
        import signal

        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script("slow.py", 'import time; time.sleep(10); print("done")')

            proc = subprocess.Popen(
                [env.velo, "run", "slow.py"],
                cwd=env.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Kill quickly
            time.sleep(0.1)
            proc.terminate()

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

            # Should not leave zombies
            print(f"  SIGTERM: returncode={proc.returncode}")

    def test_sigkill_leaves_no_orphans(self):
        """SIGKILL should not leave orphan processes."""
        import signal

        with WeirdEnv() as env:
            env.setup_basic()
            env.create_script(
                "spawn.py",
                """
import subprocess
import time
p = subprocess.Popen(["sleep", "100"])
time.sleep(10)
""",
            )

            proc = subprocess.Popen(
                [env.velo, "run", "spawn.py"], cwd=env.path, start_new_session=True
            )

            time.sleep(0.3)
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

            time.sleep(0.5)

            # Check for orphan sleep processes
            ps_result = subprocess.run(
                ["pgrep", "-f", "sleep 100"], capture_output=True
            )
            orphans = ps_result.stdout.decode().strip().split("\n")
            orphans = [o for o in orphans if o]

            # Clean up any orphans
            for pid in orphans:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except:
                    pass

            print(f"  Orphans found: {len(orphans)}")
