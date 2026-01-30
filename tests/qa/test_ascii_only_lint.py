"""
CJK-in-comments lint check.

This test ensures no CJK (Chinese/Japanese/Korean) characters appear in
Python COMMENTS. CJK in string literals is allowed for Unicode testing.
Emojis are allowed everywhere (they're for UX output).

Policy:
- Emojis: ALLOWED (they're for user-facing output)
- CJK in strings: ALLOWED (they're for Unicode testing)
- CJK in comments: FORBIDDEN (comments should be in English)

Add to CI pipeline to enforce English-only comments.
"""

import re
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

# CJK Unicode ranges (Chinese, Japanese, Korean characters)
# These should not appear in comments
CJK_PATTERN = re.compile(
    r"[\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Unified Ideographs Extension A
    r"\u3000-\u303f"  # CJK Symbols and Punctuation
    r"\uac00-\ud7af"  # Hangul Syllables (Korean)
    r"\u3040-\u309f"  # Hiragana (Japanese)
    r"\u30a0-\u30ff]"  # Katakana (Japanese)
)


def extract_comments(line: str) -> str:
    """
    Extract comment portion from a Python line.

    Returns the comment text (after #) or empty string if no comment.
    Handles # inside strings correctly.
    """
    in_string = False
    string_char = None
    i = 0
    while i < len(line):
        char = line[i]

        # Handle string literals
        if char in ('"', "'") and not in_string:
            # Check for triple quotes
            if line[i : i + 3] in ('"""', "'''"):
                in_string = True
                string_char = line[i : i + 3]
                i += 3
                continue
            else:
                in_string = True
                string_char = char
                i += 1
                continue
        elif in_string:
            if string_char and len(string_char) == 3 and line[i : i + 3] == string_char:
                in_string = False
                string_char = None
                i += 3
                continue
            elif string_char and len(string_char) == 1 and char == string_char and (i == 0 or line[i - 1] != "\\"):
                in_string = False
                string_char = None
                i += 1
                continue

        # Found a comment marker outside of strings
        if char == "#" and not in_string:
            return line[i + 1 :]

        i += 1

    return ""


def find_cjk_in_comments(filepath: Path) -> list[tuple[int, str, str]]:
    """
    Find CJK characters in comments only.

    Returns list of (line_number, char, line_content) tuples.
    """
    issues = []
    try:
        content = filepath.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), 1):
            # Extract comment portion only
            comment = extract_comments(line)

            # Check for CJK in comment
            match = CJK_PATTERN.search(comment)
            if match:
                char = match.group()
                issues.append((lineno, char, line.strip()[:80]))
    except UnicodeDecodeError:
        issues.append((0, "?", f"File is not valid UTF-8: {filepath}"))
    except Exception as e:
        issues.append((0, "?", f"Error reading file: {e}"))

    return issues


def is_excluded(filepath: Path, exclude_patterns: list[str]) -> bool:
    """Check if file matches any exclude pattern."""
    filepath_str = str(filepath)
    # Check each pattern (currently simple substring matching)
    for pattern in exclude_patterns:
        # Extract the key part of the pattern (e.g., "fixtures" from "**/fixtures/**")
        key = pattern.replace("**/", "").replace("/**", "").replace("*", "")
        if key and key in filepath_str.lower():
            return True
    return False


class TestCJKInComments:
    """Ensure no CJK characters in comments (English comments only)."""

    def test_no_cjk_in_comments(self) -> None:
        """Python comments should be in English only (no CJK characters)."""
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

                issues = find_cjk_in_comments(py_file)
                for lineno, char, line in issues:
                    rel_path = py_file.relative_to(root)
                    all_issues.append((rel_path, lineno, char, line))

        if all_issues:
            msg_lines = [
                "CJK characters found in comments (should be English):",
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

    print("Checking for CJK characters in Python comments...")
    print("=" * 60)

    total_issues = 0

    for check_dir in CHECK_DIRS:
        dir_path = root / check_dir
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            if is_excluded(py_file, EXCLUDE_PATTERNS):
                continue

            issues = find_cjk_in_comments(py_file)
            if issues:
                rel_path = py_file.relative_to(root)
                for lineno, char, line in issues:
                    print(f"{rel_path}:{lineno}: CJK in comment '{char}' (U+{ord(char):04X})")
                    print(f"  {line}")
                    total_issues += 1
                    exit_code = 1

    print("=" * 60)
    if total_issues == 0:
        print("OK: No CJK characters in comments.")
    else:
        print(f"FAIL: Found {total_issues} CJK characters in comments.")
        print("Please use English-only comments.")

    return exit_code


if __name__ == "__main__":
    sys.exit(run_check())
