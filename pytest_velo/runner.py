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


def run_single_test(nodeid: str, cov_path: str | None = None) -> dict[str, Any]:
    """
    Run a single pytest test by nodeid and return result as dict.

    Args:
        nodeid: pytest node ID (e.g., "tests/test_foo.py::TestClass::test_method")
        cov_path: Optional path for coverage collection (RFC-0028 --cov support)

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

        # BUG-002 FIX: Save CWD before test execution
        original_cwd = os.getcwd()

        # Build pytest args
        pytest_args = [
            nodeid,
            "-q",  # Quiet mode
            "--tb=short",  # Short traceback
            "-p",
            "no:cacheprovider",  # Disable cache for isolation
        ]

        # RFC-0028: Add coverage if requested
        if cov_path:
            pytest_args.extend(["--cov", cov_path, "--cov-append"])

        # Run the single test with minimal output
        try:
            exit_code = pytest.main(pytest_args)
        finally:
            # BUG-002 FIX: Restore CWD after test execution
            try:
                os.chdir(original_cwd)
            except OSError:
                pass  # Directory may have been deleted by test
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
    import argparse

    parser = argparse.ArgumentParser(description="pytest-velo single test runner")
    parser.add_argument("nodeid", help="pytest node ID to execute")
    parser.add_argument("--cov", dest="cov_path", help="Enable coverage for path")

    args = parser.parse_args()

    try:
        result = run_single_test(args.nodeid, cov_path=args.cov_path)
        print(json.dumps(result))
        return result["exit_code"]
    except Exception as e:
        print(
            json.dumps(
                {
                    "test_id": args.nodeid,
                    "passed": False,
                    "exit_code": 1,
                    "error": str(e),
                }
            )
        )
        return 1


import atexit
import os

if __name__ == "__main__":
    code = main()
    # INV-002: Child processes must use atexit._clear() and os._exit()
    # to prevent parent resource corruption from parent-registered handlers.
    atexit._clear()
    os._exit(code)
