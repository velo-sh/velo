# Phase 5.0 Fast Loader: pytest Configuration
#
# This file registers custom markers for the L0-L5 test framework.
# It is automatically loaded by pytest.

import pytest


def pytest_configure(config):
    """Register custom markers for Phase 5.0 QA framework."""
    config.addinivalue_line("markers", "smoke: L0 Smoke tests - critical path verification")
    config.addinivalue_line("markers", "happy_path: L1 Happy path tests - complete user journey")
    config.addinivalue_line("markers", "sad_path: L2 Sad path tests - error handling")
    config.addinivalue_line("markers", "config: L3 Configuration tests - CLI options")
    config.addinivalue_line("markers", "security: L4 Security tests - RFC-0006 §3 requirements")
    config.addinivalue_line("markers", "edge: L5 Edge/Chaos tests - stress testing")
    config.addinivalue_line("markers", "slow: Tests that take > 10 seconds")
    config.addinivalue_line("markers", "cli: CLI command tests")
