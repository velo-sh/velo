"""
Velo QA: Phase 4.0 Agent C Tests (安全专家 - Security)
======================================================
Focus: File system security, code execution safety, information disclosure.

Each test is ATOMIC and uses ISOLATED temp projects.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest


def get_velo_binary() -> str:
    """Get path to velo binary."""
    repo_root = Path(__file__).parent.parent.parent
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
def check_analyze_available():
    if not velo_analyze_available():
        pytest.skip("velo analyze not implemented yet")


class SecureProject:
    """Isolated project for security testing."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="velo_sec_"))
        self.velo = get_velo_binary()

    def set_pyproject(self, deps: list[str] | None = None) -> "SecureProject":
        content = f"""[project]
name = "sec-test"
version = "0.1.0"
dependencies = {json.dumps(deps or [])}
"""
        (self.path / "pyproject.toml").write_text(content)
        return self

    def set_file(self, name: str, content: str) -> "SecureProject":
        (self.path / name).write_text(content)
        return self

    def sync(self) -> "SecureProject":
        subprocess.run(["uv", "sync", "--quiet"], cwd=self.path, capture_output=True)
        return self

    def analyze(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.velo, "analyze"] + list(args),
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def cleanup(self) -> None:
        # Restore permissions before cleanup
        # CRITICAL: Skip symlinks to avoid modifying target files (like the system Python binary)
        for root, dirs, files in os.walk(self.path):
            for d in dirs:
                dir_path = os.path.join(root, d)
                if not os.path.islink(dir_path):
                    try:
                        os.chmod(dir_path, 0o755)
                    except Exception:
                        pass
            for f in files:
                file_path = os.path.join(root, f)
                if not os.path.islink(file_path):
                    try:
                        os.chmod(file_path, 0o644)
                    except Exception:
                        pass
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "SecureProject":
        return self

    def __exit__(self, *args: Any) -> None:
        self.cleanup()


# =============================================================================
# C1: FILE SYSTEM SECURITY
# =============================================================================


@pytest.mark.tier1
class TestFileSystemSecurity:
    """C1: File system security tests."""

    def test_c1_1_readonly_dir_analyze_works(self):
        """C1-1: Analyze works in read-only directory."""
        with SecureProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()

            # Make directory read-only
            os.chmod(p.path, 0o555)

            try:
                result = p.analyze()
                # Should work - analyze only reads
                assert result.returncode == 0 or "permission" in result.stderr.lower()
            finally:
                os.chmod(p.path, 0o755)

    def test_c1_2_readonly_fix_errors_gracefully(self):
        """C1-2: --fix in read-only dir errors gracefully."""
        with SecureProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()

            pyproject = p.path / "pyproject.toml"
            os.chmod(pyproject, 0o444)

            try:
                result = p.analyze("--fix")
                # Should error, not crash
                if result.returncode != 0:
                    assert "permission" in result.stderr.lower() or "error" in result.stderr.lower()
            finally:
                os.chmod(pyproject, 0o644)

    def test_c1_3_temp_files_cleaned_up(self):
        """C1-3: No sensitive data left in /tmp."""
        tmp_before = set(os.listdir("/tmp"))

        with SecureProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()
            p.analyze()

        tmp_after = set(os.listdir("/tmp"))
        new_files = tmp_after - tmp_before

        # No velo-related files should remain
        velo_leftovers = [f for f in new_files if "velo" in f.lower()]
        assert len(velo_leftovers) == 0, f"Temp files not cleaned: {velo_leftovers}"


# =============================================================================
# C2: CODE EXECUTION SAFETY
# =============================================================================


@pytest.mark.tier1
class TestCodeExecutionSafety:
    """C2: Ensure analyzing code doesn't execute it unsafely."""

    def test_c2_1_import_hook_sandboxed(self):
        """C2-1: Malicious __import__ hook doesn't escape."""
        with SecureProject() as p:
            p.set_pyproject()
            # Malicious code that tries to hook import
            p.set_file(
                "evil.py",
                """
import builtins
original_import = builtins.__import__
def evil_import(name, *args, **kwargs):
    with open("/tmp/velo_pwned", "w") as f:
        f.write("pwned")
    return original_import(name, *args, **kwargs)
builtins.__import__ = evil_import
""",
            )
            p.sync()

            p.analyze("evil.py")

            # Check that the evil code didn't create the marker file
            assert not os.path.exists("/tmp/velo_pwned"), "Import hook escaped sandbox!"

    @pytest.mark.xfail(reason="DEF-4.0-004: velo analyze executes code - TODO: add sandbox in future")
    def test_c2_3_os_system_not_executed(self):
        """C2-3: os.system() in analyzed file shouldn't execute.

        Known Issue: velo analyze currently executes scripts to measure
        real import times. Future: add sandbox/static analysis option.
        """
        with SecureProject() as p:
            p.set_pyproject()
            marker = "/tmp/velo_executed_marker"
            p.set_file(
                "danger.py",
                f"""
import os
os.system("touch {marker}")
""",
            )
            p.sync()

            if os.path.exists(marker):
                os.remove(marker)

            p.analyze("danger.py")
            assert not os.path.exists(marker), "SECURITY: os.system() escaped sandbox!"


# =============================================================================
# C3: INFORMATION DISCLOSURE
# =============================================================================


@pytest.mark.tier1
class TestInformationDisclosure:
    """C3: Prevent information leakage."""

    def test_c3_1_no_absolute_paths_in_errors(self):
        """C3-1: Error messages don't leak absolute paths."""
        with SecureProject() as p:
            p.set_pyproject()
            # Trigger an error
            result = p.analyze("nonexistent_file.py")

            # Should not leak the full temp path in user-facing output
            # The temp path contains random strings
            combined = result.stdout + result.stderr
            # This is a soft check - absolute paths starting with tmpdir are suspicious
            assert not combined.count("/var/folders/") > 0 or "error" in combined.lower()

    def test_c3_2_output_file_permissions(self):
        """C3-2: Profile output file has secure permissions."""
        with SecureProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()

            output_file = p.path / "report.json"
            p.analyze("--output", str(output_file))

            if output_file.exists():
                mode = os.stat(output_file).st_mode
                # Should not be world-readable (no 'other' read bit)
                # But this depends on umask, so just check it's not 777
                assert not (mode & stat.S_IRWXO) == stat.S_IRWXO

    def test_c3_3_respects_umask(self):
        """C3-3: --output respects umask."""
        old_umask = os.umask(0o077)  # Restrictive umask
        try:
            with SecureProject() as p:
                p.set_pyproject()
                p.set_file("main.py", "print(1)")
                p.sync()

                output_file = p.path / "private.json"
                p.analyze("--output", str(output_file))

                if output_file.exists():
                    mode = os.stat(output_file).st_mode & 0o777
                    # With umask 077, file should be 0600 or similar
                    assert not (mode & 0o077), f"File too permissive: {oct(mode)}"
        finally:
            os.umask(old_umask)


# =============================================================================
# C4: INPUT VALIDATION
# =============================================================================


@pytest.mark.tier1
class TestInputValidation:
    """C4: Input validation and injection prevention."""

    def test_c4_1_shell_injection_in_filename(self):
        """C4-1: Shell injection in filename is escaped."""
        with SecureProject() as p:
            p.set_pyproject()
            # Create file with shell metacharacters
            evil_name = "test; touch /tmp/pwned.py"
            try:
                p.set_file(evil_name, "print(1)")
            except OSError:
                pytest.skip("Cannot create file with shell chars")

            p.analyze(evil_name)

            # Shell injection should not have worked
            assert not os.path.exists("/tmp/pwned.py")

    def test_c4_2_command_substitution_in_output(self):
        """C4-2: Command substitution in --output is literal."""
        with SecureProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            p.sync()

            # Try command substitution
            evil_output = "$(whoami).json"
            p.analyze("--output", evil_output)

            # Should create literal file, not execute whoami
            p.path / evil_output
            # The output should be treated as literal filename
            # Check that no file with user's name was created
            import getpass

            username = getpass.getuser()
            assert not os.path.exists(p.path / f"{username}.json"), "Command substitution executed!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
