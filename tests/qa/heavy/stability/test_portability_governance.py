import os
from pathlib import Path


def test_no_hardcoded_absolute_paths():
    """
    Governance Test: Ensures no hardcoded absolute paths to the current
    workspace exist in the source or documentation.
    """
    repo_root = Path(__file__).parents[4].resolve()
    repo_root_str = str(repo_root)

    # Paths to ignore
    ignored_dirs = {
        ".git",
        "target",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".antigravity",
        "build",
        ".velo_cache",
    }

    # Extensions to check
    check_extensions = {".rs", ".py", ".md", ".toml", ".json", ".sh", ".yml", ".yaml"}

    failures = []

    for root, dirs, files in os.walk(repo_root):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]

        for file in files:
            file_path = Path(root) / file

            # Skip this test file itself
            if file_path == Path(__file__).resolve():
                continue

            if file_path.suffix in check_extensions:
                try:
                    with open(file_path, encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, 1):
                            if repo_root_str in line:
                                # Special case: allow if it's a comment explaining this rule or a relative link with file://./
                                # But actually repo_root_str is /Users/... so it shouldn't be in file://./ anyway
                                failures.append(f"{file_path}:{line_no}: {line.strip()}")
                except Exception as e:
                    print(f"Warning: Could not read {file_path}: {e}")

    if failures:
        msg = f"Found {len(failures)} hardcoded absolute paths to the repo root:\n"
        msg += "\n".join(failures[:20])  # Limit output
        if len(failures) > 20:
            msg += f"\n... and {len(failures) - 20} more."
        msg += "\n\nHelp: Use relative paths or dynamic discovery (e.g. Path(__file__)) instead."
        pytest_fail(msg)


def pytest_fail(msg):
    import pytest

    pytest.fail(msg)
