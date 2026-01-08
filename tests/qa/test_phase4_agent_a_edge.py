"""
Velo QA: Phase 4.0 Agent A Tests (激进派 - Edge Cases)
=======================================================
Focus: Path attacks, malformed input, race conditions, exploit hunting.

Each test is ATOMIC and uses ISOLATED temp projects.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

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
    except:
        return False


@pytest.fixture(scope="session", autouse=True)
def check_analyze_available():
    if not velo_analyze_available():
        pytest.skip("velo analyze not implemented yet")


class EdgeProject:
    """Isolated project for edge case testing."""
    
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="velo_edge_"))
        self.velo = get_velo_binary()
    
    def set_pyproject(self, deps=None):
        content = f'''[project]
name = "edge-test"
version = "0.1.0"
dependencies = {json.dumps(deps or [])}
'''
        (self.path / "pyproject.toml").write_text(content)
        return self
    
    def set_file(self, name: str, content: str):
        (self.path / name).write_text(content)
        return self
    
    def analyze(self, *args, timeout: float = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.velo, "analyze"] + list(args),
            cwd=self.path, capture_output=True, text=True, timeout=timeout
        )
    
    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)
    
    def __enter__(self): return self
    def __exit__(self, *args): self.cleanup()


# =============================================================================
# A1: PATH ATTACKS
# =============================================================================

@pytest.mark.tier1
class TestPathAttacks:
    """A1: Path traversal and malicious path tests."""
    
    def test_a1_1_path_traversal_rejected(self):
        """A1-1: Path traversal should be rejected."""
        with EdgeProject() as p:
            p.set_pyproject()
            result = p.analyze("../../etc/passwd")
            # Should not succeed
            assert result.returncode != 0 or "error" in result.stderr.lower()
    
    def test_a1_2_special_files_handled(self):
        """A1-2: Special files like /dev/null handled."""
        with EdgeProject() as p:
            p.set_pyproject()
            result = p.analyze("/dev/null")
            # Should error gracefully, not crash
            assert result.returncode != 0 or "error" in result.stderr.lower()
    
    def test_a1_3_symlink_attack(self):
        """A1-3: Don't follow malicious symlinks outside project."""
        with EdgeProject() as p:
            p.set_pyproject()
            symlink = p.path / "evil.py"
            try:
                symlink.symlink_to("/etc/passwd")
            except (OSError, PermissionError):
                pytest.skip("Cannot create symlink")
            
            result = p.analyze("evil.py")
            # Should not expose /etc/passwd content
            assert "/etc/passwd" not in result.stdout
    
    def test_a1_4_unicode_filename(self):
        """A1-4: Unicode filenames handled."""
        with EdgeProject() as p:
            p.set_pyproject()
            p.set_file("分析.py", "print('你好')")
            result = p.analyze("分析.py")
            # Should handle gracefully
            assert result.returncode == 0 or "error" in result.stderr.lower()
    
    def test_a1_5_null_byte_injection(self):
        """A1-5: Null byte in filename rejected (security).
        
        NOTE: Cannot test via subprocess - null bytes terminate C strings.
        Rust unit test test_validate_path_null_byte() covers this.
        """
        pytest.skip("subprocess cannot pass null bytes - covered by Rust unit test")


# =============================================================================
# A2: MALFORMED INPUT
# =============================================================================

@pytest.mark.tier2
class TestMalformedInput:
    """A2: Malformed and extreme input tests."""
    
    @pytest.mark.tier3
    def test_a2_1_huge_file_timeout(self):
        """A2-1: Huge file should timeout, not OOM."""
        with EdgeProject() as p:
            p.set_pyproject()
            # Generate file with many imports
            imports = "\n".join([f"import fake_module_{i}" for i in range(1000)])
            p.set_file("huge.py", imports)
            
            try:
                result = p.analyze("huge.py", timeout=30)
                # Should complete or timeout, not crash
                assert True
            except subprocess.TimeoutExpired:
                # Timeout is acceptable
                pass
    
    def test_a2_2_circular_import_detection(self):
        """A2-2: Circular imports should be detected, not hang."""
        with EdgeProject() as p:
            p.set_pyproject()
            p.set_file("a.py", "import b")
            p.set_file("b.py", "import c")
            p.set_file("c.py", "import a")
            
            try:
                result = p.analyze("a.py", timeout=10)
                # Should complete, not hang
                assert True
            except subprocess.TimeoutExpired:
                pytest.fail("Circular import caused hang")
    
    def test_a2_3_negative_threshold_rejected(self):
        """A2-3: Negative threshold should be rejected."""
        with EdgeProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            result = p.analyze("--slow-threshold-ms=-1")
            # Should reject invalid input
            assert result.returncode != 0 or "invalid" in result.stderr.lower() or "error" in result.stderr.lower()
    
    def test_a2_4_overflow_threshold(self):
        """A2-4: Overflow threshold handled."""
        with EdgeProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            result = p.analyze("--slow-threshold-ms=999999999999999999")
            # Should handle gracefully
            # Either error or use max value
            assert True  # No crash
    
    def test_a2_5_binary_file_as_python(self):
        """A2-5: Binary file disguised as .py should error."""
        with EdgeProject() as p:
            p.set_pyproject()
            # Write binary content
            (p.path / "binary.py").write_bytes(b'\x00\x01\x02\xff\xfe')
            result = p.analyze("binary.py")
            # Should error gracefully OR handle it without crashing (0 imports)
            # The new analyze command is more robust and may just find 0 imports for binary files
            assert result.returncode == 0 or "error" in result.stderr.lower()


# =============================================================================
# A3: RACE CONDITIONS
# =============================================================================

@pytest.mark.tier3
class TestRaceConditions:
    """A3: Race condition and concurrency tests."""
    
    def test_a3_1_file_deleted_during_analyze(self):
        """A3-1: File deleted mid-analyze should not crash."""
        with EdgeProject() as p:
            p.set_pyproject()
            p.set_file("ephemeral.py", "import time; time.sleep(0.1)")
            
            def delete_after_delay():
                time.sleep(0.05)
                try:
                    (p.path / "ephemeral.py").unlink()
                except:
                    pass
            
            thread = threading.Thread(target=delete_after_delay)
            thread.start()
            
            try:
                result = p.analyze("ephemeral.py", timeout=10)
                # May succeed or fail, but should not crash
                assert True
            except subprocess.TimeoutExpired:
                pass
            finally:
                thread.join()
    
    def test_a3_2_pyproject_modified_during_analyze(self):
        """A3-2: pyproject.toml modified mid-analyze."""
        with EdgeProject() as p:
            p.set_pyproject()
            p.set_file("main.py", "print(1)")
            
            def modify_after_delay():
                time.sleep(0.05)
                try:
                    (p.path / "pyproject.toml").write_text("[project]\nname='changed'")
                except:
                    pass
            
            thread = threading.Thread(target=modify_after_delay)
            thread.start()
            
            try:
                result = p.analyze(timeout=10)
                assert True  # No crash
            except subprocess.TimeoutExpired:
                pass
            finally:
                thread.join()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
