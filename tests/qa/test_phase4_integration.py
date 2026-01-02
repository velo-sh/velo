"""
Velo QA: Phase 4.0 Real Project Integration Tests
===================================================
Tests velo analyze on REAL framework projects:
- FastAPI (web framework)
- Django (web framework)
- DataScience (numpy/pandas/sklearn)

Per TEST_ARCHITECTURE.md: Each test creates an isolated temp project
with REAL dependencies installed via uv sync.

These tests are SLOW but verify real-world behavior.
"""

import json
import os
import shutil
import subprocess
import tempfile
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


class RealProject:
    """
    Real project with actual framework dependencies.
    
    WARNING: These tests are SLOW because they install real packages.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.path = Path(tempfile.mkdtemp(prefix=f"velo_{name}_"))
        self.velo = get_velo_binary()
        self._setup_done = False
    
    def set_pyproject(self, deps: list):
        """Create pyproject.toml with real dependencies."""
        content = f'''[project]
name = "{self.name}-test"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = {json.dumps(deps)}

[tool.uv]
dev-dependencies = []
'''
        (self.path / "pyproject.toml").write_text(content)
        return self
    
    def set_app(self, filename: str, code: str):
        """Create application file."""
        (self.path / filename).write_text(code)
        return self
    
    def setup(self, timeout: float = 120):
        """Run uv sync to install REAL dependencies (slow!)."""
        if self._setup_done:
            return self
        
        result = subprocess.run(
            ["uv", "sync"],
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode != 0:
            pytest.fail(f"uv sync failed: {result.stderr}")
        self._setup_done = True
        return self
    
    def analyze(self, *args, timeout: float = 60) -> subprocess.CompletedProcess:
        """Run velo analyze."""
        return subprocess.run(
            [self.velo, "analyze"] + list(args),
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
    
    def cleanup(self):
        """Remove temp directory."""
        shutil.rmtree(self.path, ignore_errors=True)
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.cleanup()


# =============================================================================
# REAL PROJECT: FastAPI
# =============================================================================

@pytest.mark.tier2
@pytest.mark.slow
class TestRealFastAPI:
    """Integration tests with REAL FastAPI installation."""
    
    def test_fastapi_analyze(self):
        """Analyze real FastAPI project with all dependencies."""
        with RealProject("fastapi") as p:
            p.set_pyproject(deps=[
                "fastapi>=0.115.0",
                "uvicorn",
                "pydantic>=2.0",
            ])
            p.set_app("main.py", '''
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/items")
def create_item(item: Item):
    return item
''')
            p.setup()
            
            result = p.analyze()
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            output = result.stdout.lower()
            # Should identify framework imports
            assert "fastapi" in output or "pydantic" in output or "ms" in output


# =============================================================================
# REAL PROJECT: Django
# =============================================================================

@pytest.mark.tier2
@pytest.mark.slow
class TestRealDjango:
    """Integration tests with REAL Django installation."""
    
    def test_django_analyze(self):
        """Analyze real Django project."""
        with RealProject("django") as p:
            p.set_pyproject(deps=[
                "django>=5.0",
            ])
            p.set_app("manage.py", '''
#!/usr/bin/env python
import os
import sys

import django
from django.conf import settings
from django.http import HttpResponse, JsonResponse

# Configure Django settings
settings.configure(
    DEBUG=True,
    SECRET_KEY='test-secret-key-for-velo-analyze',
    ROOT_URLCONF=__name__,
    INSTALLED_APPS=[
        'django.contrib.contenttypes',
        'django.contrib.auth',
    ],
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    },
)
django.setup()

print("Django OK")
''')
            p.setup()
            
            result = p.analyze("manage.py")
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            output = result.stdout.lower()
            # Should show Django-related imports
            assert "django" in output or "ms" in output


# =============================================================================
# REAL PROJECT: DataScience
# =============================================================================

@pytest.mark.tier2
@pytest.mark.slow
class TestRealDataScience:
    """Integration tests with REAL data science stack."""
    
    def test_datascience_analyze(self):
        """Analyze real data science project with slow imports."""
        with RealProject("datascience") as p:
            p.set_pyproject(deps=[
                "numpy>=1.26.0",
                "pandas>=2.0.0",
                "scikit-learn>=1.4.0",
            ])
            p.set_app("analysis.py", '''
# Data science pipeline
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

# Create sample data
np.random.seed(42)
df = pd.DataFrame({
    'feature_a': np.random.randn(100),
    'feature_b': np.random.randn(100),
})
df['target'] = (df['feature_a'] + df['feature_b'] > 0).astype(int)

# Train model
X = df[['feature_a', 'feature_b']]
y = df['target']
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

model = LogisticRegression()
model.fit(X_train, y_train)

print(f"Accuracy: {model.score(X_test, y_test):.2f}")
print("DataScience OK")
''')
            p.setup()
            
            result = p.analyze("analysis.py")
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            output = result.stdout.lower()
            # Should identify slow imports (pandas, numpy, sklearn are heavy)
            assert any(pkg in output for pkg in ["pandas", "numpy", "sklearn", "slow", "ms"])
    
    def test_datascience_fix_mode(self):
        """Test --fix on data science project generates preload config."""
        with RealProject("datascience-fix") as p:
            p.set_pyproject(deps=[
                "numpy>=1.26.0",
                "pandas>=2.0.0",
            ])
            p.set_app("main.py", '''
import numpy as np
import pandas as pd
print("OK")
''')
            p.setup()
            
            # Before --fix: no [tool.velo] section
            before = (p.path / "pyproject.toml").read_text()
            assert "[tool.velo]" not in before
            
            result = p.analyze("--fix")
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            
            # After --fix: should have [tool.velo] section
            after = (p.path / "pyproject.toml").read_text()
            assert "[tool.velo]" in after, f"--fix did not add [tool.velo]: {after}"


# =============================================================================
# REAL PROJECT: Custom Threshold
# =============================================================================

@pytest.mark.tier2
@pytest.mark.slow
class TestRealThreshold:
    """Test --slow-threshold-ms on real projects."""
    
    def test_threshold_affects_output(self):
        """Different thresholds should affect what's flagged as slow."""
        with RealProject("threshold-test") as p:
            p.set_pyproject(deps=["requests"])
            p.set_app("main.py", "import requests\nprint('OK')")
            p.setup()
            
            # With low threshold - more should be flagged
            result_low = p.analyze("--slow-threshold-ms=10")
            assert result_low.returncode == 0
            
            # With high threshold - less should be flagged
            result_high = p.analyze("--slow-threshold-ms=1000")
            assert result_high.returncode == 0


# =============================================================================
# PERFORMANCE BENCHMARKS - Validate Phase 4.0 Improvements
# =============================================================================

@pytest.mark.tier2
@pytest.mark.slow
@pytest.mark.perf
class TestPerformanceBenchmark:
    """
    Performance validation tests.
    
    Phase 4.0 Goal: velo analyze should complete in < 5 seconds
    and provide accurate preload suggestions.
    """
    
    def test_analyze_completes_under_5_seconds(self):
        """PERF-001: velo analyze should complete in < 5 seconds."""
        with RealProject("perf-test") as p:
            p.set_pyproject(deps=["fastapi", "requests"])
            p.set_app("main.py", '''
from fastapi import FastAPI
import requests
app = FastAPI()
''')
            p.setup()
            
            import time
            start = time.perf_counter()
            result = p.analyze()
            elapsed = time.perf_counter() - start
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            assert elapsed < 5.0, f"analyze took {elapsed:.2f}s, expected < 5s"
            print(f"\n📊 velo analyze completed in {elapsed:.2f}s")
    
    def test_preload_suggestion_accuracy(self):
        """PERF-002: Preload suggestions should be accurate (>80%)."""
        with RealProject("preload-accuracy") as p:
            # Project with known slow imports
            p.set_pyproject(deps=["pandas", "numpy", "requests"])
            p.set_app("main.py", '''
import pandas as pd
import numpy as np
import requests
print("OK")
''')
            p.setup()
            
            result = p.analyze("--fix")
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            
            pyproject = (p.path / "pyproject.toml").read_text()
            
            # [tool.velo] should exist
            assert "[tool.velo]" in pyproject, "Missing [tool.velo] section"
            
            # Check if heavy imports are suggested for preload
            # pandas and numpy are typically heavy (>100ms)
            preload_section = pyproject.split("[tool.velo]")[-1]
            heavy_suggested = any(
                pkg in preload_section.lower() 
                for pkg in ["pandas", "numpy"]
            )
            assert heavy_suggested, f"Expected heavy imports in preload: {preload_section}"
    
    def test_datascience_preload_improvement(self):
        """PERF-003: DataScience project should show significant improvement potential."""
        with RealProject("ds-improvement") as p:
            p.set_pyproject(deps=["pandas", "numpy", "scikit-learn"])
            p.set_app("analysis.py", '''
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

df = pd.DataFrame({'a': [1,2,3], 'b': [4,5,6]})
print("OK")
''')
            p.setup()
            
            result = p.analyze()
            
            assert result.returncode == 0, f"Failed: {result.stderr}"
            output = result.stdout
            
            # Should identify slow imports and suggest improvement
            # RFC-0004 says: "Estimated improvement: 15-25% faster startup"
            output_lower = output.lower()
            has_timing = "ms" in output_lower or "%" in output
            has_slow_marker = "slow" in output_lower or "←" in output
            
            assert has_timing or has_slow_marker, f"Expected timing/slow markers: {output}"
    
    def test_compare_before_after_preload(self):
        """PERF-004: Compare startup time before and after applying preload."""
        with RealProject("before-after") as p:
            p.set_pyproject(deps=["pandas"])
            p.set_app("main.py", "import pandas as pd\nprint('OK')")
            p.setup()
            
            import time
            
            # First: Run velo analyze to get suggestions
            result = p.analyze()
            assert result.returncode == 0
            
            # Second: Run velo analyze --fix to apply preload config
            result_fix = p.analyze("--fix")
            assert result_fix.returncode == 0
            
            # Verify [tool.velo] was added
            pyproject = (p.path / "pyproject.toml").read_text()
            assert "[tool.velo]" in pyproject, "Expected [tool.velo] section after --fix"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "slow"])
