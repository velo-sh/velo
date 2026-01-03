import pytest

def pytest_configure(config):
    """Register custom markers for Phase 5.2 QA."""
    config.addinivalue_line("markers", "happy_path: Marks tests for standard successful operations")
    config.addinivalue_line("markers", "sad_path: Marks tests for expected failure modes")
    config.addinivalue_line("markers", "config: Marks tests for configuration parsing")
    config.addinivalue_line("markers", "security: Marks tests for security vulnerabilities")
    config.addinivalue_line("markers", "stability: Marks tests for extreme load or long-term stability")
    config.addinivalue_line("markers", "perf: Marks performance and timing tests")
