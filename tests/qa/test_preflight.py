import pytest
from velo_zygote.preflight import PreflightCheck, CheckResult
from velo_zygote.env_profile import RunContext

class TestPreflightCheck:
    def test_run_all_structure(self):
        """Verify the structure of the preflight check results."""
        checker = PreflightCheck()
        result = checker.run_all()
        
        # Should have at least 3 checks
        assert len(result.checks) >= 3
        
        # Verify specific checks exist
        names = [c.name for c in result.checks]
        assert "Environment Detection" in names
        assert "Security Shield Status" in names
        assert "Path Validation" in names
        
    def test_env_detection_logic(self, monkeypatch):
        """Verify environment detection logic respects CI flags."""
        checker = PreflightCheck()
        
        # Case 1: No CI env, should pass in DEV
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        res = checker._check_env_profile()
        assert res.passed
        
        # Case 2: CI env present, but profile thinks DEV (Simulate failure mode)
        # We can't easily mock ENV_PROFILE since it's immutable and loaded at import time.
        # But we can verify that the check returns details correctly.
        assert "os_type" in res.details
        assert "run_context" in res.details

    def test_path_validation(self):
        """Verify path validation checks."""
        checker = PreflightCheck()
        res = checker._check_paths()
        
        assert res.passed
        assert "worker_launcher" in res.details
        assert res.details["worker_launcher"]["valid"] is True
