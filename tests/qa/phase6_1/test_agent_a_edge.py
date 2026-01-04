# Agent A (Edge Case Hunter) - Phase 6.1 Serve & Analyze
# 激进派 QA: "Break it before users do."

import pytest
import os
import subprocess
from pathlib import Path


@pytest.mark.tier1
class TestAgentAEdge:
    """Agent A: Edge Case Hunter for Phase 6.1 velo serve."""

    # ===== EDGE-61-SERVE: CLI Edge Cases =====

    @pytest.mark.skip(reason="Awaiting D1: CLI argument hardening implementation")
    def test_EDGE_61_SERVE_001_long_app_path(self, isolated_env):
        """Very long app path (4096 chars)."""
        long_path = "a" * 4096 + ":app"
        result = isolated_env.run_velo("serve", long_path, timeout=2)
        assert result.returncode != 0

    @pytest.mark.skip(reason="Awaiting P1: detect_app.py implementation")
    def test_EDGE_61_SERVE_002_unicode_app_name(self, isolated_env):
        """Unicode characters in app/module names."""
        env = isolated_env
        env.create_app("中文模块.py", "from fastapi import FastAPI; app = FastAPI()")
        result = env.run_velo("serve", "中文模块:app", "--dry-run", timeout=2)
        # Should either work or give clear error
        assert result.returncode == 0 or "invalid" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting D1: CLI argument hardening implementation")
    def test_EDGE_61_SERVE_003_multiple_colons(self, isolated_env):
        """Multiple colons in app specifier."""
        result = isolated_env.run_velo("serve", "path:to:module:app", timeout=2)
        assert result.returncode != 0
        assert "invalid" in result.stderr.lower() or "colon" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting D1: CLI argument hardening implementation")
    def test_EDGE_61_SERVE_004_empty_module(self, isolated_env):
        """Empty module name."""
        result = isolated_env.run_velo("serve", ":app", timeout=2)
        assert result.returncode != 0

    @pytest.mark.skip(reason="Awaiting D1: CLI argument hardening implementation")
    def test_EDGE_61_SERVE_005_empty_app(self, isolated_env):
        """Empty app name."""
        result = isolated_env.run_velo("serve", "main:", timeout=2)
        assert result.returncode != 0

    # ===== EDGE-61-DETECT: Framework Detection Edge Cases =====

    @pytest.mark.skip(reason="Awaiting P1: detect_app.py implementation")
    def test_EDGE_61_DETECT_001_multiple_apps(self, isolated_env):
        """Multiple FastAPI instances in one file."""
        env = isolated_env
        env.create_app("main.py", """
from fastapi import FastAPI
app1 = FastAPI()
app2 = FastAPI()
app3 = FastAPI()
""")
        result = env.run_velo("serve", "--dry-run", timeout=2)
        # Should detect first or report ambiguity
        assert result.returncode == 0 or "ambiguous" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting P1: detect_app.py implementation")
    def test_EDGE_61_DETECT_002_no_app_found(self, isolated_env):
        """No app in main.py."""
        env = isolated_env
        env.create_app("main.py", "print('hello')")
        result = env.run_velo("serve", "--dry-run", timeout=2)
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "detect" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting P2: Factory pattern detection")
    def test_EDGE_61_DETECT_003_nested_factory(self, isolated_env):
        """create_app() inside a class."""
        env = isolated_env
        env.create_app("main.py", """
from fastapi import FastAPI

class AppFactory:
    def create_app(self):
        return FastAPI()
""")
        result = env.run_velo("serve", "--dry-run", timeout=2)
        # Factory detection is limited to module scope
        assert result.returncode != 0 or "factory" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting P2: Factory pattern detection")
    def test_EDGE_61_DETECT_004_conditional_app(self, isolated_env):
        """App created inside conditional."""
        env = isolated_env
        env.create_app("main.py", """
from fastapi import FastAPI
import os

if os.environ.get('DEBUG'):
    app = FastAPI()
""")
        result = env.run_velo("serve", "--dry-run", timeout=2)
        # Static analysis may not find this
        assert result.returncode != 0 or "conditional" in result.stderr.lower()

    # ===== EDGE-61-WATCH: File Watcher Edge Cases =====

    @pytest.mark.skip(reason="Awaiting D6/D7: File watcher implementation")
    def test_EDGE_61_WATCH_001_rapid_changes(self, isolated_env):
        """100 file changes in 1 second - debounce must handle."""
        env = isolated_env
        env.create_fastapi_app()
        # This test would start serve in background and rapidly touch files
        # Verify no crash and debounce works (single restart, not 100)
        pass

    @pytest.mark.skip(reason="Awaiting D6: File watcher implementation")
    def test_EDGE_61_WATCH_002_symlink_modification(self, isolated_env):
        """Modify file through symlink."""
        pass

    @pytest.mark.skip(reason="Awaiting D6: File watcher implementation")
    def test_EDGE_61_WATCH_003_delete_watched_directory(self, isolated_env):
        """Delete src/ while server running."""
        pass

    @pytest.mark.skip(reason="Awaiting D6: File watcher implementation")
    def test_EDGE_61_WATCH_004_rename_watched_file(self, isolated_env):
        """Rename main.py to app.py."""
        pass

    @pytest.mark.skip(reason="Awaiting D6: File watcher implementation")
    def test_EDGE_61_WATCH_005_permission_denied(self, isolated_env):
        """chmod 000 main.py while running."""
        pass

    # ===== EDGE-61-DX: DX Excellence Tests [GAP-09/10] =====

    @pytest.mark.skip(reason="Awaiting D11: strsim typo suggestions")
    def test_EDGE_61_DX_001_typo_suggestions(self, isolated_env):
        """--relod → 'Did you mean --reload?'"""
        result = isolated_env.run_velo("serve", "--relod", timeout=2)
        assert result.returncode != 0
        assert "did you mean" in result.stderr.lower() or "reload" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting D12: Source-pointing diagnostics")
    def test_EDGE_61_DX_002_source_pointing_error(self, isolated_env):
        """Error shows main.py:42:10 format."""
        env = isolated_env
        env.create_app("main.py", "syntax error here")
        result = env.run_velo("serve", "--dry-run", timeout=2)
        # Should contain line:column or line_number reference
        assert ":" in result.stderr or "line" in result.stderr.lower()

    @pytest.mark.skip(reason="Awaiting D10: UX polish implementation")
    def test_EDGE_61_A11Y_001_ascii_only_terminal(self, isolated_env):
        """TERM=dumb produces valid output without unicode."""
        env = isolated_env
        env.create_fastapi_app()
        env_vars = {"TERM": "dumb"}
        result = env.run_velo("serve", "--dry-run", env=env_vars, timeout=2)
        # Should not contain box-drawing characters
        assert "─" not in result.stdout
        assert "│" not in result.stdout

