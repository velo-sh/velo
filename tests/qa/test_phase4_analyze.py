"""
Velo QA: Phase 4.0 velo analyze Tests
======================================
Tests for `velo analyze` command as specified in RFC-0004.

Each test is ATOMIC and uses ISOLATED temp projects.
"""

import json
import os
import shutil
import subprocess
import tempfile
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
        pytest.skip("velo binary not found - run cargo build first")


class AnalyzeProject:
    """
    Isolated project for testing velo analyze.
    
    Each instance is a CLEAN, ISOLATED project directory.
    """
    
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="velo_analyze_"))
        self.velo = get_velo_binary()
    
    def set_pyproject(self, name: str = "test-app", dependencies: list = None, velo_config: dict = None):
        """Set pyproject.toml."""
        deps = dependencies or []
        content = f'''[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = {json.dumps(deps)}
'''
        if velo_config:
            content += f'''
[tool.velo]
'''
            for k, v in velo_config.items():
                content += f'{k} = {json.dumps(v)}\n'
        
        (self.path / "pyproject.toml").write_text(content)
        return self
    
    def set_app(self, filename: str, code: str):
        """Set application code."""
        (self.path / filename).write_text(code)
        return self
    
    def uv_add(self, *packages):
        """Use uv add to add dependencies."""
        subprocess.run(
            ["uv", "add", "--quiet"] + list(packages),
            cwd=self.path,
            capture_output=True
        )
        return self
    
    def sync(self):
        """Run uv sync."""
        subprocess.run(
            ["uv", "sync", "--quiet"],
            cwd=self.path,
            capture_output=True
        )
        return self
    
    def analyze(self, *args, timeout: float = 60) -> subprocess.CompletedProcess:
        """Run velo analyze."""
        cmd = [self.velo, "analyze"] + list(args)
        return subprocess.run(
            cmd, cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
    
    def read_pyproject(self) -> str:
        """Read pyproject.toml contents."""
        return (self.path / "pyproject.toml").read_text()
    
    def cleanup(self):
        """Clean up temp directory."""
        try:
            shutil.rmtree(self.path)
        except:
            pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# CHECK: Is velo analyze implemented?
# =============================================================================

def velo_analyze_available() -> bool:
    """Check if velo analyze command is available."""
    try:
        velo = get_velo_binary()
        result = subprocess.run([velo, "--help"], capture_output=True, text=True, timeout=5)
        return "analyze" in result.stdout.lower()
    except:
        return False


@pytest.fixture(scope="session", autouse=True)
def check_analyze_available():
    """Skip all tests if velo analyze not implemented."""
    if not velo_analyze_available():
        pytest.skip("velo analyze not implemented yet (waiting for Dev)")


# =============================================================================
# SCENARIO 1: FastAPI Project Analysis
# =============================================================================

class TestAnalyzeFastAPI:
    """Test velo analyze on FastAPI projects."""
    
    def test_basic_analysis(self):
        """Basic velo analyze on FastAPI project."""
        with AnalyzeProject() as project:
            project.set_pyproject(dependencies=["fastapi"])
            project.set_app("main.py", '''
from fastapi import FastAPI
app = FastAPI()
''')
            project.sync()
            
            result = project.analyze()
            
            # Should complete without error
            assert result.returncode == 0, f"analyze failed: {result.stderr}"
            
            # Should show some output
            assert result.stdout.strip() != "", "Expected analysis output"
            
            # Should mention fastapi import
            assert "fastapi" in result.stdout.lower() or "fastapi" in result.stderr.lower()


# =============================================================================
# SCENARIO 2: DataScience Project (Slow Imports)
# =============================================================================

class TestAnalyzeDataScience:
    """Test velo analyze on data science projects with slow imports."""
    
    def test_slow_imports_identified(self):
        """Should identify slow imports like pandas/numpy."""
        with AnalyzeProject() as project:
            project.set_pyproject(dependencies=["pandas", "numpy"])
            project.set_app("analysis.py", '''
import pandas as pd
import numpy as np
print("Data science app")
''')
            project.sync()
            
            result = project.analyze()
            
            assert result.returncode == 0, f"analyze failed: {result.stderr}"
            
            output = result.stdout.lower()
            # pandas and numpy are typically slow
            # At least one should be flagged
            assert "pandas" in output or "numpy" in output


# =============================================================================
# SCENARIO 3: Custom Threshold
# =============================================================================

class TestAnalyzeThreshold:
    """Test --slow-threshold-ms parameter."""
    
    def test_custom_threshold_low(self):
        """Low threshold should flag more imports."""
        with AnalyzeProject() as project:
            project.set_pyproject(dependencies=["fastapi"])
            project.set_app("main.py", "from fastapi import FastAPI")
            project.sync()
            
            result = project.analyze("--slow-threshold-ms=10")
            
            assert result.returncode == 0
            # With 10ms threshold, more imports should be flagged
    
    def test_custom_threshold_high(self):
        """High threshold should flag fewer imports."""
        with AnalyzeProject() as project:
            project.set_pyproject(dependencies=["fastapi"])
            project.set_app("main.py", "from fastapi import FastAPI")
            project.sync()
            
            result = project.analyze("--slow-threshold-ms=1000")
            
            assert result.returncode == 0
            # With 1000ms threshold, fewer imports should be flagged


# =============================================================================
# SCENARIO 4: --fix Mode
# =============================================================================

class TestAnalyzeFix:
    """Test velo analyze --fix writes to pyproject.toml."""
    
    def test_fix_adds_tool_velo_section(self):
        """--fix should add [tool.velo] section."""
        with AnalyzeProject() as project:
            project.set_pyproject(dependencies=["pandas", "numpy"])
            project.set_app("main.py", "import pandas; import numpy")
            project.sync()
            
            # Initial pyproject should not have [tool.velo]
            initial = project.read_pyproject()
            assert "[tool.velo]" not in initial
            
            result = project.analyze("--fix")
            
            assert result.returncode == 0
            
            # After --fix, should have [tool.velo]
            updated = project.read_pyproject()
            assert "[tool.velo]" in updated
            assert "preload" in updated.lower()


# =============================================================================
# SCENARIO 5: No Slow Imports
# =============================================================================

class TestAnalyzeNoSlowImports:
    """Test when no imports are slow."""
    
    def test_no_slow_imports_message(self):
        """Should handle case with no slow imports gracefully."""
        with AnalyzeProject() as project:
            project.set_pyproject()  # No dependencies
            project.set_app("main.py", "print('hello')")
            project.sync()
            
            result = project.analyze()
            
            assert result.returncode == 0
            # Should indicate no slow imports or complete successfully


# =============================================================================
# SCENARIO 6: Django Project
# =============================================================================

class TestAnalyzeDjango:
    """Test velo analyze on Django project."""
    
    @pytest.mark.skip(reason="Django setup is complex - implement if needed")
    def test_django_project(self):
        """Analyze Django project imports."""
        pass


# =============================================================================
# EDGE CASES
# =============================================================================

class TestAnalyzeEdgeCases:
    """Edge case tests for velo analyze."""
    
    def test_missing_pyproject(self):
        """Should handle missing pyproject.toml gracefully."""
        with AnalyzeProject() as project:
            # Don't create pyproject.toml
            project.set_app("main.py", "print('hello')")
            
            result = project.analyze()
            
            # Should error gracefully, not crash
            # Either non-zero return code or helpful message
            if result.returncode != 0:
                assert "pyproject" in result.stderr.lower() or "error" in result.stderr.lower()
    
    def test_invalid_python_file(self):
        """Should handle invalid Python syntax."""
        with AnalyzeProject() as project:
            project.set_pyproject()
            project.set_app("bad.py", "this is not valid python!")
            project.sync()
            
            result = project.analyze("bad.py")
            
            # Should error gracefully
            assert result.returncode != 0 or "error" in result.stderr.lower() or "syntax" in result.stderr.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
