"""
SSOT Audit Test (INV-SSOT-001)

This test verifies that `velo_zygote/constants.py` is correctly
generated from `config/constants.toml` by `build.rs`.

TDD Approach:
- RED: Test fails if constants.py diverges from constants.toml
- GREEN: Test passes when build.rs keeps them in sync
"""

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    import toml as tomllib  # Python < 3.11 fallback


class TestSSOTIntegrity:
    """Verify Single Source of Truth for shared constants."""

    @pytest.fixture
    def project_root(self) -> Path:
        """Get project root directory."""
        return Path(__file__).parents[2]

    @pytest.fixture
    def constants_toml(self, project_root: Path) -> dict:
        """Load constants from TOML source of truth."""
        toml_path = project_root / "config" / "constants.toml"
        assert toml_path.exists(), f"SSOT file missing: {toml_path}"
        try:
            # Python 3.11+ tomllib uses binary mode
            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        except TypeError:
            # Python < 3.11 toml uses text mode
            with open(toml_path) as f:
                return tomllib.load(f)

    @pytest.fixture
    def constants_py_values(self, project_root: Path) -> dict:
        """Extract constant values from generated Python file."""
        py_path = project_root / "velo_zygote" / "constants.py"
        assert py_path.exists(), f"Generated file missing: {py_path}"

        # Parse Python file to extract constants
        # We use a simple regex approach to avoid import side effects
        import re

        content = py_path.read_text()

        # Extract KEY = value patterns (simple types only)
        pattern = r"^([A-Z][A-Z0-9_]+)\s*=\s*(.+)$"
        values = {}
        for line in content.split("\n"):
            match = re.match(pattern, line)
            if match:
                key = match.group(1)
                val_str = match.group(2).strip()
                # Parse value
                if val_str.startswith('"') or val_str.startswith("'"):
                    values[key] = val_str.strip("\"'")
                elif val_str.isdigit():
                    values[key] = int(val_str)
                elif val_str.replace(".", "").isdigit():
                    values[key] = float(val_str)
        return values

    def test_protocol_version_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Protocol version must match."""
        assert constants_py_values.get("PROTOCOL_VERSION") == constants_toml.get("protocol_version"), (
            "PROTOCOL_VERSION mismatch between TOML and Python"
        )

    def test_max_message_size_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Max message size must match."""
        assert constants_py_values.get("MAX_MESSAGE_SIZE") == constants_toml.get("max_message_size"), (
            "MAX_MESSAGE_SIZE mismatch between TOML and Python"
        )

    def test_socket_path_limit_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Socket path limit must match."""
        assert constants_py_values.get("SOCKET_PATH_LIMIT") == constants_toml.get("socket_path_limit"), (
            "SOCKET_PATH_LIMIT mismatch between TOML and Python"
        )

    def test_socket_startup_timeout_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Socket startup timeout must match."""
        assert constants_py_values.get("SOCKET_STARTUP_TIMEOUT") == constants_toml.get("socket_startup_timeout"), (
            "SOCKET_STARTUP_TIMEOUT mismatch between TOML and Python"
        )

    def test_graceful_shutdown_timeout_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Graceful shutdown timeout must match."""
        assert constants_py_values.get("GRACEFUL_SHUTDOWN_TIMEOUT") == constants_toml.get(
            "graceful_shutdown_timeout"
        ), "GRACEFUL_SHUTDOWN_TIMEOUT mismatch between TOML and Python"

    def test_default_port_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Default port must match."""
        assert constants_py_values.get("DEFAULT_PORT") == constants_toml.get("default_port"), (
            "DEFAULT_PORT mismatch between TOML and Python"
        )

    def test_security_base_env_whitelist_sync(self, constants_toml: dict, constants_py_values: dict):
        """[INV-SSOT-001] Security base env whitelist must match."""
        assert constants_py_values.get("SECURITY_BASE_ENV_WHITELIST") == constants_toml.get(
            "security_base_env_whitelist"
        ), "SECURITY_BASE_ENV_WHITELIST mismatch between TOML and Python"

    def test_constants_py_is_auto_generated(self, project_root: Path):
        """[INV-SSOT-001] constants.py must have auto-generated header."""
        py_path = project_root / "velo_zygote" / "constants.py"
        content = py_path.read_text()
        assert "Auto-generated by build.rs" in content, (
            "constants.py missing auto-generated header - manual edit detected!"
        )
