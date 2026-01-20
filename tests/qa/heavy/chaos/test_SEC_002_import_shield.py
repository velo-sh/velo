import importlib
import os
import sys
import unittest

import pytest

# Defer import to avoid collection-time failure when VELO_ENV is not set
# This is a "hostile" test that requires the full Velo environment
try:
    from velo_zygote import shield

    SHIELD_AVAILABLE = True
except (ValueError, ModuleNotFoundError, ImportError):
    shield = None
    SHIELD_AVAILABLE = False


@pytest.mark.skipif(not SHIELD_AVAILABLE, reason="Requires VELO_ENV to be set by Rust supervisor")
class TestImportShieldHostile(unittest.TestCase):
    def setUp(self):
        # [RITUAL 11.2] Hostile Test Technical Hygiene
        # 1. Environment Clearing: Always manually clear sys.modules for target packages
        for mod in list(sys.modules.keys()):
            if mod.startswith("velo_") or mod in ["os", "subprocess", "builtins"]:
                sys.modules.pop(mod, None)

        # 2. Reset singleton active flags
        if hasattr(shield.ImportShield, "_active"):
            shield.ImportShield._active = False

        # 3. Finder Synchronization: Ensure meta_path is clean before start
        sys.meta_path = [x for x in sys.meta_path if not isinstance(x, shield.ImportShield)]

    def tearDown(self):
        # [RITUAL 11.2] Restoration Checklist
        shield.ImportShield._active = False
        sys.meta_path = [x for x in sys.meta_path if not isinstance(x, shield.ImportShield)]
        # Re-clear to prevent poisoning subsequent tests
        for mod in list(sys.modules.keys()):
            if mod.startswith("velo_"):
                sys.modules.pop(mod, None)
        # Restore os/subprocess if they were popped (optional but good)
        importlib.invalidate_caches()

    def test_shield_logic_internals(self):
        """Verify shield blocks velo_zygote.* imports"""

        # Install shield
        shield.ImportShield.install()
        shield.ImportShield._active = True

        # 1. Enforce Mode (Default)
        os.environ["VELO_SHIELD_MODE"] = "enforce"

        # [RITUAL 11.2] Finder Synchronization Verification
        self.assertIsInstance(
            sys.meta_path[0],
            shield.ImportShield,
            "CRITICAL: ImportShield is NOT at the top of sys.meta_path (Ritual 11.2 Violation)",
        )

        finder = sys.meta_path[0]

        # Should raise ImportError in find_spec
        with self.assertRaises(ImportError) as cm:
            spec = finder.find_spec("velo_zygote.internal_secret", None)
        self.assertIn("Unauthorized access", str(cm.exception))

        with self.assertRaises(ImportError) as cm:
            finder.find_spec("velo_zygote.constants", None)
        self.assertIn("Unauthorized access", str(cm.exception))

        # 2. Dry Run Mode
        os.environ["VELO_SHIELD_MODE"] = "dry_run"
        spec = finder.find_spec("velo_zygote.constants", None)
        self.assertIsNone(spec)  # Should allow

        spec = finder.find_spec("os", None)
        self.assertIsNone(spec)  # Should allow

    def test_shield_logic_os(self):
        """Verify if shield blocks 'os' as per QA Handoff Requirements (P0)"""
        # REQUIRED BY: docs/qa/handover_qa_phase_1_5.md §3.E
        # REQUIREMENT: Worker imports os -> Assertion: Import FAILS (ImportError)

        shield.ImportShield.install()
        shield.ImportShield._active = True
        os.environ["VELO_SHIELD_MODE"] = "enforce"

        finder = [x for x in sys.meta_path if isinstance(x, shield.ImportShield)][0]

        # Handoff says: Worker imports os -> Assertion: Import FAILS.

        # We expect ImportError (Unauthorized access)
        with self.assertRaises(ImportError) as cm:
            finder.find_spec("os", None)

        self.assertIn("Unauthorized access", str(cm.exception))

        # If we reach here, verification passed.
        print("\n[HOSTILE] Analysis Confirmed: 'os' IS blocked by ImportShield.")


if __name__ == "__main__":
    unittest.main()
