"""
Phase 7.1 QA Test Configuration

Provides shared fixtures for RFC-0018 Integrated Custody tests.
"""

import os
import sys
from pathlib import Path

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "tier2: RFC-0017 Tier 2 E2E tests (>100ms, <10s)"
    )


@pytest.fixture(scope="session")
def workspace_root():
    """Get the workspace root directory."""
    return Path(__file__).parent.parent.parent.parent


@pytest.fixture(scope="session") 
def velo_binary(workspace_root):
    """Get path to velo binary."""
    release = workspace_root / "target" / "release" / "velo"
    debug = workspace_root / "target" / "debug" / "velo"
    
    if release.exists():
        return str(release)
    elif debug.exists():
        return str(debug)
    else:
        pytest.skip("velo binary not found")
