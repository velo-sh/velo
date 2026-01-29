"""
ASCII-only code lint check.

This test ensures no non-ASCII characters (like Chinese, emoji, etc.)
appear in Python source files. All comments and strings should be in English.

Add to CI pipeline to prevent non-ASCII characters from being committed.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

# Directories to check (ALL source code - Python and Rust)
CHECK_DIRS = [
    # Rust source
    "crates",
    # Python source
    "velo_zygote",
    "python",
    "pytest_velo",
    "scripts",
    # Tests
    "tests",
    # Benchmarks
    "benchmarks",
    # Examples
    "examples",
    # Fuzz tests
    "fuzz",
]


# Files to exclude (e.g., test fixtures that intentionally contain Unicode)
EXCLUDE_PATTERNS = [
    "**/fixtures/**",
    "**/test_data/**",
    "**/__pycache__/**",
]


def find_non_ascii_in_file(filepath: Path) -> list[tuple[int, str, str]]:
    """
    Find non-ASCII characters in a file.

    Returns list of (line_number, char, line_content) tuples.
    """
    issues = []
    try:
        content = filepath.read_text(encoding='utf-8')
        for lineno, line in enumerate(content.splitlines(), 1):
            # Find non-ASCII characters
            for i, char in enumerate(line):
                if ord(char) > 127:
                    # Skip if inside a string literal that's for testing UTF-8
                    # (e.g., test cases that deliberately test Unicode handling)
                    issues.append((lineno, char, line.strip()[:80]))
                    break  # One issue per line is enough
    except UnicodeDecodeError:
        issues.append((0, "?", f"File is not valid UTF-8: {filepath}"))
    except Exception as e:
        issues.append((0, "?", f"Error reading file: {e}"))

    return issues


def is_excluded(filepath: Path, exclude_patterns: list[str]) -> bool:
    """Check if file matches any exclude pattern."""
    filepath_str = str(filepath)
    for pattern in exclude_patterns:
        # Simple glob matching
        if "fixtures" in filepath_str.lower():
            return True
        if "test_data" in filepath_str.lower():
            return True
        if "__pycache__" in filepath_str:
            return True
    return False


class TestAsciiOnlyCode:
    """Ensure all source code contains only ASCII characters."""

    def test_no_non_ascii_in_source(self) -> None:
        """All Python source files should contain only ASCII characters."""
        root = Path(__file__).parent.parent.parent

        all_issues: list[tuple[Path, int, str, str]] = []

        # Check directories
        for check_dir in CHECK_DIRS:
            dir_path = root / check_dir
            if not dir_path.exists():
                continue

            for py_file in dir_path.rglob("*.py"):
                if is_excluded(py_file, EXCLUDE_PATTERNS):
                    continue

                issues = find_non_ascii_in_file(py_file)
                for lineno, char, line in issues:
                    rel_path = py_file.relative_to(root)
                    all_issues.append((rel_path, lineno, char, line))



        if all_issues:
            msg_lines = [
                "Non-ASCII characters found in source code:",
                "=" * 60,
            ]
            for filepath, lineno, char, line in all_issues[:20]:  # Limit output
                msg_lines.append(f"  {filepath}:{lineno}: '{char}' (U+{ord(char):04X})")
                msg_lines.append(f"    {line}")
            if len(all_issues) > 20:
                msg_lines.append(f"  ... and {len(all_issues) - 20} more issues")
            msg_lines.append("=" * 60)
            msg_lines.append("Please use English-only comments and ASCII characters.")

            pytest.fail("\n".join(msg_lines))



def run_check() -> int:
    """Run the check as a standalone script."""
    root = Path(__file__).parent.parent.parent
    exit_code = 0

    print("Checking for non-ASCII characters in Python source files...")
    print("=" * 60)

    total_issues = 0

    for check_dir in CHECK_DIRS:
        dir_path = root / check_dir
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            if is_excluded(py_file, EXCLUDE_PATTERNS):
                continue

            issues = find_non_ascii_in_file(py_file)
            if issues:
                rel_path = py_file.relative_to(root)
                for lineno, char, line in issues:
                    print(f"{rel_path}:{lineno}: Non-ASCII '{char}' (U+{ord(char):04X})")
                    print(f"  {line}")
                    total_issues += 1
                    exit_code = 1

    print("=" * 60)
    if total_issues == 0:
        print("OK: All source files contain ASCII-only characters.")
    else:
        print(f"FAIL: Found {total_issues} non-ASCII character issues.")
        print("Please use English-only comments.")

    return exit_code


if __name__ == "__main__":
    sys.exit(run_check())
