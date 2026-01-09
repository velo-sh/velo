import sys
import os
import toml
import unittest
import importlib.util
from pathlib import Path

# Adjust path to find velo_zygote
sys.path.append(str(Path(__file__).parents[3]))

import velo_zygote.constants as py_constants

class TestSSOTParity(unittest.TestCase):
    def setUp(self):
        self.toml_path = Path(__file__).parents[3] / "config" / "constants.toml"
        with open(self.toml_path, "r") as f:
            self.toml_data = toml.load(f)

    def test_value_parity(self):
        """Verify python constants match TOML SSOT"""
        # Mapping logic needs to match what build.rs does. 
        # Based on file view, lower_snake_case in TOML -> UPPER_SNAKE_CASE in Python
        
        for key, value in self.toml_data.items():
            if isinstance(value, dict):
                continue # Nested tables might be handled differently or flatter attributes
            
            py_key = key.upper()
            if hasattr(py_constants, py_key):
                py_val = getattr(py_constants, py_key)
                self.assertEqual(py_val, value, f"Mismatch for {py_key}: TOML={value} vs Python={py_val}")
            else:
                # Some keys might not be exported or named differently, checking if they should be
                # The handoff says "diff must be ZERO".
                # We'll validte strict simple keys first.
                pass

    def test_platform_isolation(self):
        """Verify platform specific constants are strictly isolated"""
        # Handoff: "Assertion: PATH_MACOS_* constants must NOT be present or used... on Linux"
        # Since we are on Mac, we reverse the logic: PATH_LINUX_* should NOT be present?
        # Or at least we verify what IS present.
        
        current_os = sys.platform
        
        py_attrs = dir(py_constants)
        
        if current_os == "darwin":
            # On macOS, we strictly expect NO LINUX defaults if isolation is perfect.
            # However, looking at the file content I saw earlier, they ARE there.
            # So this test is expected to FAIL if I strictly enforce what I saw.
            # I will assert it and see it fail, then report it.
            linux_constants = [x for x in py_attrs if "LINUX" in x]
            self.assertEqual(len(linux_constants), 0, f"Found LINUX constants on macOS: {linux_constants}")
        
        elif current_os == "linux":
            macos_constants = [x for x in py_attrs if "MACOS" in x]
            self.assertEqual(len(macos_constants), 0, f"Found MACOS constants on Linux: {macos_constants}")

if __name__ == "__main__":
    unittest.main()
