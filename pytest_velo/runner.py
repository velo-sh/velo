"""
pytest-velo Test Runner: Single test execution for Zygote dispatch

RFC-0028: Invoked by Zygote to run a single test item
Usage: python runner.py <test_nodeid>
Output: JSON result to stdout
"""

import json
import sys
import time
from io import StringIO
from typing import Any


def run_single_test(nodeid: str) -> dict[str, Any]:
    """
    Run a single pytest test by nodeid and return result as dict.

    Args:
        nodeid: pytest node ID (e.g., "tests/test_foo.py::TestClass::test_method")

    Returns:
        dict with keys: test_id, passed, exit_code, duration_ms, stdout, stderr
    """
    import pytest

    start = time.perf_counter()

    # Capture stdout/stderr
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    # Save originals
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    try:
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Run the single test with minimal output
        exit_code = pytest.main(
            [
                nodeid,
                "-q",  # Quiet mode
                "--tb=short",  # Short traceback
                "-p",
                "no:cacheprovider",  # Disable cache for isolation
            ]
        )
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    duration_ms = (time.perf_counter() - start) * 1000

    return {
        "test_id": nodeid,
        "passed": exit_code == 0,
        "exit_code": int(exit_code),
        "duration_ms": round(duration_ms, 2),
        "stdout": stdout_capture.getvalue() or None,
        "stderr": stderr_capture.getvalue() or None,
    }


def main() -> int:
    """Entry point: run test from CLI arg and print JSON result."""
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "error": "Usage: python runner.py <test_nodeid>",
                    "passed": False,
                    "exit_code": 2,
                }
            )
        )
        return 2

    nodeid = sys.argv[1]

    try:
        result = run_single_test(nodeid)
        print(json.dumps(result))
        return result["exit_code"]
    except Exception as e:
        print(
            json.dumps(
                {
                    "test_id": nodeid,
                    "passed": False,
                    "exit_code": 1,
                    "error": str(e),
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
