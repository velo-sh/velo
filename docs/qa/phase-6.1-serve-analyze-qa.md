# Phase 6.1 QA Test Plan

> **RFC**: [RFC-0010](../rfcs/0010-phase-6.1-serve-analyze.md)  
> **Author**: QA Expert  
> **Date**: 2026-01-04  
> **Status**: APPROVED

---

## 1. Test Matrix

| Test Category | macOS | Linux | Docker | CI |
|---------------|-------|-------|--------|-----|
| Unit tests | ✅ | ✅ | - | ✅ |
| Integration (uvicorn) | ✅ | ✅ | - | ✅ |
| Integration (gunicorn) | ✅ | ✅ | - | ✅ |
| File watcher (FSEvents) | ✅ | - | - | ✅ (macOS) |
| File watcher (inotify) | - | ✅ | - | ✅ (Linux) |
| Container polling | - | - | ✅ | ✅ |
| Signal handling | ✅ | ✅ | ✅ | ✅ |
| Security validation | ✅ | ✅ | - | ✅ |

## 2. Coverage Targets

| Module | Target |
|--------|--------|
| `src/serve/runner.rs` | 80% |
| `src/serve/framework.rs` | 90% |
| `src/cmd/serve.rs` | 85% |
| `python/detect_app.py` | 95% |
| Security validation | **100%** |

---

## 3. Security Test Cases (P0)

### 3.1 Command Injection (SEC-P0-001)

```python
# tests/security/test_command_injection.py
import pytest
from subprocess import run

class TestCommandInjection:
    """SEC-P0-001: Verify shell metacharacters are rejected."""
    
    @pytest.mark.parametrize("app", [
        "main:app; rm -rf /",
        "main:app | cat /etc/passwd",
        "main:app && whoami",
        "main:app`id`",
        "main:$(cat /etc/passwd)",
        "main:app\nid",
    ])
    def test_rejects_shell_metacharacters(self, app):
        result = run(["velo", "serve", app], capture_output=True, text=True)
        assert result.returncode != 0
        assert "metacharacters" in result.stderr.lower() or "invalid" in result.stderr.lower()
```

### 3.2 Path Traversal (SEC-P0-002)

```python
# tests/security/test_path_traversal.py

class TestPathTraversal:
    """SEC-P0-002: Verify path traversal is blocked."""
    
    def test_rejects_parent_directory(self, tmp_path):
        result = run(["velo", "serve", "--detect-in", "../../../etc"], 
                     cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode != 0
        assert "within project" in result.stderr.lower()
    
    def test_rejects_symlink_escape(self, tmp_path):
        # Create symlink pointing outside project
        outside = tmp_path / ".." / "outside"
        link = tmp_path / "link"
        link.symlink_to(outside)
        
        result = run(["velo", "serve", "--detect-in", str(link)],
                     cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode != 0
```

### 3.3 PID File Safety (SEC-P0-003)

```python
# tests/security/test_pid_file.py

class TestPidFileSafety:
    """SEC-P0-003: Verify PID file is created safely."""
    
    def test_rejects_existing_file(self, tmp_path):
        pid_file = tmp_path / "velo.pid"
        pid_file.write_text("12345")
        
        result = run(["velo", "serve", "--pid-file", str(pid_file)],
                     capture_output=True, text=True, timeout=2)
        assert result.returncode != 0
        assert "exists" in result.stderr.lower()
    
    def test_rejects_symlink(self, tmp_path):
        target = tmp_path / "target"
        symlink = tmp_path / "velo.pid"
        symlink.symlink_to(target)
        
        result = run(["velo", "serve", "--pid-file", str(symlink)],
                     capture_output=True, text=True, timeout=2)
        assert result.returncode != 0
```

---

## 4. Performance Tests (P0)

### 4.1 Instant Restart Latency

```python
# tests/performance/test_restart_latency.py
import time

class TestInstantRestartPerformance:
    """Verify restart meets <50ms target."""
    
    TARGET_MS = 50
    
    def test_restart_latency(self, fastapi_project, velo_serve):
        # Start server
        process = velo_serve(fastapi_project)
        wait_for_ready(process, timeout=5)
        
        # Measure restart time
        start = time.perf_counter()
        (fastapi_project / "main.py").touch()
        wait_for_restart(process, timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        assert elapsed_ms < self.TARGET_MS, \
            f"Restart took {elapsed_ms:.1f}ms, target <{self.TARGET_MS}ms"
    
    @pytest.mark.benchmark
    def test_restart_latency_p95(self, fastapi_project, velo_serve):
        """P95 latency should be under 100ms."""
        process = velo_serve(fastapi_project)
        wait_for_ready(process)
        
        latencies = []
        for _ in range(20):
            start = time.perf_counter()
            (fastapi_project / "main.py").touch()
            wait_for_restart(process)
            latencies.append((time.perf_counter() - start) * 1000)
            time.sleep(0.5)  # Cooldown
        
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 100, f"P95 latency {p95:.1f}ms exceeds 100ms"
```

### 4.2 Startup Timing Accuracy

```python
class TestStartupTiming:
    """Verify timing display is accurate."""
    
    def test_timing_breakdown_sums_correctly(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run"], 
                     cwd=fastapi_project, capture_output=True, text=True)
        
        timing = parse_timing_output(result.stdout)
        expected_total = timing.load + timing.graph + timing.init
        
        assert abs(timing.total - expected_total) <= 2, \
            f"Total {timing.total}ms != sum {expected_total}ms"
```

---

## 5. Test Fixtures

```python
# tests/conftest.py
import pytest
import subprocess
import random
from pathlib import Path

@pytest.fixture
def fastapi_project(tmp_path):
    """Create minimal FastAPI project."""
    (tmp_path / "main.py").write_text("""
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
""")
    
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "test-project"
dependencies = ["fastapi", "uvicorn"]
""")
    
    return tmp_path

@pytest.fixture
def django_project(tmp_path):
    """Create minimal Django WSGI project."""
    (tmp_path / "wsgi.py").write_text("""
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
""")
    
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "test-django"
dependencies = ["django", "gunicorn"]
""")
    
    return tmp_path

@pytest.fixture
def velo_serve():
    """Start/stop velo serve process."""
    processes = []
    
    def _start(project_dir, port=None, **kwargs):
        port = port or random.randint(10000, 60000)
        cmd = ["velo", "serve", "--port", str(port)]
        proc = subprocess.Popen(
            cmd, cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        processes.append(proc)
        return proc
    
    yield _start
    
    for proc in processes:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

def wait_for_ready(proc, timeout=10):
    """Wait for server to be ready."""
    import time
    start = time.time()
    while time.time() - start < timeout:
        if b"Listening" in proc.stdout.read1(1024):
            return True
        time.sleep(0.1)
    raise TimeoutError("Server not ready")

def wait_for_restart(proc, timeout=5):
    """Wait for restart message."""
    import time
    start = time.time()
    while time.time() - start < timeout:
        if b"Restarted" in proc.stdout.read1(1024):
            return True
        time.sleep(0.05)
    raise TimeoutError("Restart not detected")
```

---

## 6. Error Message Tests

```python
# tests/test_error_messages.py

class TestErrorMessages:
    """Verify error messages are helpful and actionable."""
    
    def test_missing_uvicorn_suggests_fix(self, tmp_path):
        (tmp_path / "main.py").write_text("from fastapi import FastAPI; app = FastAPI()")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\ndependencies=['fastapi']")
        
        result = run(["velo", "serve"], cwd=tmp_path, capture_output=True, text=True)
        
        assert "uvicorn" in result.stderr.lower()
        assert "uv add" in result.stderr or "pip install" in result.stderr
    
    def test_port_in_use_shows_number(self):
        import socket
        sock = socket.socket()
        sock.bind(('127.0.0.1', 18888))
        sock.listen(1)
        
        try:
            result = run(["velo", "serve", "--port", "18888"], 
                        capture_output=True, text=True, timeout=2)
            assert "18888" in result.stderr
            assert "in use" in result.stderr.lower()
        finally:
            sock.close()
    
    def test_no_app_shows_candidates(self, tmp_path):
        (tmp_path / "foo.py").write_text("x = 1")
        
        result = run(["velo", "serve"], cwd=tmp_path, capture_output=True, text=True)
        
        assert "Did you mean" in result.stderr or "No app found" in result.stderr
```

---

## 7. CI Regression Workflow

```yaml
# .github/workflows/phase-6.1-qa.yml
name: Phase 6.1 QA

on:
  push:
    paths:
      - 'src/serve/**'
      - 'src/cmd/serve.rs'
      - 'python/detect_app.py'
  pull_request:
    paths:
      - 'src/serve/**'

jobs:
  unit-tests:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ['3.10', '3.11', '3.12']
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: cargo test --lib
      - run: pytest tests/unit/

  security-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cargo build --release
      - run: pytest tests/security/ -v

  performance-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cargo build --release
      - run: pytest tests/performance/ -v --benchmark

  smoke-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cargo build --release
      - run: ./scripts/smoke_test.sh
```

---

## 8. Smoke Test Script

```bash
#!/bin/bash
# scripts/smoke_test.sh
set -e

echo "=== Velo Serve Smoke Test ==="

# Setup
WORK_DIR=$(mktemp -d)
trap "rm -rf $WORK_DIR" EXIT

# Create test project
cat > $WORK_DIR/main.py << 'EOF'
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}
EOF

cat > $WORK_DIR/pyproject.toml << 'EOF'
[project]
name = "smoke-test"
dependencies = ["fastapi", "uvicorn"]
EOF

# Start server
cd $WORK_DIR
timeout 15s velo serve --port 18080 &
PID=$!
sleep 3

# Verify
RESPONSE=$(curl -s http://localhost:18080/)
echo "Response: $RESPONSE"

# Cleanup
kill $PID 2>/dev/null || true

# Check result
if echo "$RESPONSE" | grep -q "ok"; then
    echo "✅ Smoke test PASSED"
    exit 0
else
    echo "❌ Smoke test FAILED"
    exit 1
fi
```

---

## 9. Accessibility Tests (Added 2026-01-04)

```python
# tests/accessibility/test_no_color.py

class TestNoColorSupport:
    """A11Y-P1-001: Verify NO_COLOR environment variable support."""
    
    def test_no_color_disables_ansi(self):
        result = run(["velo", "serve", "--dry-run"], 
                    capture_output=True, text=True,
                    env={**os.environ, "NO_COLOR": "1"})
        assert "\x1b[" not in result.stdout  # No ANSI escape codes
    
    def test_term_dumb_disables_color(self):
        result = run(["velo", "serve", "--dry-run"],
                    capture_output=True, text=True,
                    env={**os.environ, "TERM": "dumb"})
        assert "\x1b[" not in result.stdout
    
    def test_piped_output_no_color(self):
        # When stdout is not a TTY, should disable colors
        result = run(["velo", "serve", "--dry-run"],
                    capture_output=True, text=True)
        # In subprocess, stdout is not a TTY, should auto-disable


class TestTextFallbacks:
    """A11Y-P0-001: Verify icons have text labels."""
    
    def test_success_has_text_label(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run"], 
                    cwd=fastapi_project, capture_output=True, text=True)
        # Should have [OK] or similar text label, not just emoji
        assert "OK" in result.stdout or "success" in result.stdout.lower()
    
    def test_error_has_text_label(self):
        result = run(["velo", "serve", "nonexistent:app"],
                    capture_output=True, text=True)
        # Should have ERROR or FAIL text label
        assert "error" in result.stderr.lower() or "fail" in result.stderr.lower()
```

---

## 10. DX/CLI UX Tests (Added 2026-01-04)

```python
# tests/dx/test_error_formats.py

class TestSourcePointingErrors:
    """DX-P0-001: Verify errors show source location (Rust-style)."""
    
    def test_detection_error_shows_file(self, tmp_path):
        (tmp_path / "bad.py").write_text("not a valid app")
        result = run(["velo", "serve"], cwd=tmp_path,
                    capture_output=True, text=True)
        
        # Should point to the file
        assert "bad.py" in result.stderr or "-->" in result.stderr


class TestDidYouMean:
    """DX-P0-002: Verify typo suggestions (Clap-style)."""
    
    @pytest.mark.parametrize("typo,expected", [
        ("--relod", "--reload"),
        ("--por", "--port"),
        ("--host", None),  # Not a typo
    ])
    def test_suggests_similar_flag(self, typo, expected):
        result = run(["velo", "serve", typo], capture_output=True, text=True)
        
        if expected:
            assert expected in result.stderr


class TestVerbosityLevels:
    """DX-P0-004: Verify verbosity levels work correctly."""
    
    def test_default_minimal_output(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run"], 
                    cwd=fastapi_project, capture_output=True, text=True)
        assert "DEBUG" not in result.stdout
    
    def test_v_shows_timing(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run", "-v"],
                    cwd=fastapi_project, capture_output=True, text=True)
        assert "ms" in result.stdout or "Timing" in result.stdout
    
    def test_vv_shows_debug(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run", "-vv"],
                    cwd=fastapi_project, capture_output=True, text=True)
        # Should show more details
        assert len(result.stdout) > 100  # More verbose


class TestStructuredOutput:
    """DX-P0-005: Verify JSON and plain output formats."""
    
    def test_json_output_parseable(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run", "--output-format", "json"],
                    cwd=fastapi_project, capture_output=True, text=True)
        
        for line in result.stdout.strip().splitlines():
            if line.strip():
                import json
                json.loads(line)  # Should not raise
    
    def test_plain_output_no_emoji(self, fastapi_project):
        result = run(["velo", "serve", "--dry-run", "--output-format", "plain"],
                    cwd=fastapi_project, capture_output=True, text=True)
        
        assert "✨" not in result.stdout
        assert "🟢" not in result.stdout
        assert "⚡" not in result.stdout
```

---

## 11. Performance Threshold Tests (Added 2026-01-04)

```python
# tests/performance/test_thresholds.py
import time
import psutil

class TestPerformanceThresholds:
    """PERF-P0-001: Verify performance meets documented thresholds."""
    
    COLD_STARTUP_MAX_MS = 20
    RESTART_MAX_MS = 50
    MEMORY_MAX_MB = 50
    
    def test_cold_startup_under_threshold(self, fastapi_project):
        start = time.perf_counter()
        result = run(["velo", "serve", "--dry-run"], 
                    cwd=fastapi_project, capture_output=True)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        assert result.returncode == 0
        assert elapsed_ms < self.COLD_STARTUP_MAX_MS, \
            f"Cold startup {elapsed_ms:.1f}ms > {self.COLD_STARTUP_MAX_MS}ms target"
    
    def test_memory_under_threshold(self, fastapi_project):
        proc = subprocess.Popen(
            ["velo", "serve", "--port", "18999"],
            cwd=fastapi_project,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(2)  # Let it stabilize
        
        try:
            ps = psutil.Process(proc.pid)
            memory_mb = ps.memory_info().rss / 1024 / 1024
            
            assert memory_mb < self.MEMORY_MAX_MB, \
                f"Memory {memory_mb:.1f}MB > {self.MEMORY_MAX_MB}MB target"
        finally:
            proc.terminate()
            proc.wait()


class TestScalingLimits:
    """PERF-P0-003: Verify scaling behavior documented."""
    
    def test_warns_at_5k_files(self, tmp_path):
        # Create 5001 Python files
        for i in range(5001):
            (tmp_path / f"file_{i}.py").write_text(f"x = {i}")
        
        (tmp_path / "main.py").write_text("from fastapi import FastAPI; app = FastAPI()")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\ndependencies=['fastapi','uvicorn']")
        
        result = run(["velo", "serve", "--dry-run", "-v"],
                    cwd=tmp_path, capture_output=True, text=True)
        
        # Should warn about large file count
        assert "warning" in result.stderr.lower() or "5000" in result.stderr
```

---

## 12. QA Findings Summary (Updated)

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| QA-P0-001 | Platform test matrix | P0 | §1 |
| QA-P0-002 | Security test cases | P0 | §3 |
| QA-P0-003 | Performance benchmarks | P0 | §4 |
| QA-P0-004 | Regression test suite | P0 | §7 |
| QA-P0-005 | Accessibility tests | P0 | §9 *(NEW)* |
| QA-P0-006 | DX error format tests | P0 | §10 *(NEW)* |
| QA-P0-007 | Performance thresholds | P0 | §11 *(NEW)* |
| QA-P1-001 | Smoke test for CI | P1 | §8 |
| QA-P1-002 | Test fixtures | P1 | §5 |
| QA-P1-003 | Error message tests | P1 | §6 |
| QA-P1-004 | Coverage targets | P1 | §2 |
| QA-P1-005 | Structured output tests | P1 | §10 |

---

**Last Updated**: 2026-01-04 (Second Pass after RFC updates)

**Status**: Test plan ready for implementation alongside RFC-0010.

