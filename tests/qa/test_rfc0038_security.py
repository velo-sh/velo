"""
RFC-0038: Security Tests (L4) - Secrets Sanitizer

Tests environment variable redaction.
"""

import os

import pytest


@pytest.mark.tier1
def test_SEC_038_001_key_redaction(velo_test_env):
    """SEC_038_001: API_KEY redacted to ***."""
    env = velo_test_env

    script = env.home / "test.py"
    script.write_text('print("done")')

    report = env.home / "report.md"

    env_vars = os.environ.copy()
    env_vars["TEST_API_KEY"] = "super_secret_123"

    result = env.run_velo("run", f"--prof-md={report}", str(script), env=env_vars)

    assert result.returncode == 0
    content = report.read_text()

    assert "TEST_API_KEY" in content, "Env var name should be shown"
    assert "super_secret_123" not in content, "Secret value leaked!"
    assert "***" in content, "Redaction marker not found"


@pytest.mark.tier1
def test_SEC_038_all_redactions(velo_test_env):
    """Test all sensitive keywords: KEY, SECRET, TOKEN, PASSWORD."""
    env = velo_test_env

    script = env.home / "test.py"
    script.write_text('print("done")')

    report = env.home / "report.md"

    env_vars = os.environ.copy()
    env_vars["TEST_API_KEY"] = "secret_key_123"
    env_vars["DB_SECRET"] = "secret_pass_456"
    env_vars["AUTH_TOKEN"] = "token_789"
    env_vars["MYSQL_PASSWORD"] = "password_abc"

    result = env.run_velo("run", f"--prof-md={report}", str(script), env=env_vars)

    assert result.returncode == 0
    content = report.read_text()

    # All secrets should be redacted
    assert "secret_key_123" not in content
    assert "secret_pass_456" not in content
    assert "token_789" not in content
    assert "password_abc" not in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
