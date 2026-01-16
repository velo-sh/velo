import os
import re
import unittest
from pathlib import Path

class TestGovernanceAlignment(unittest.TestCase):
    """Systemic audit for SPEC-0005 (SSOT) and SPEC-0006 (Governance)."""

    def setUp(self):
        self.root = Path(__file__).parent.parent.parent
        self.src = self.root / "src"

    def test_SPEC_0006_naming_prefixes(self):
        """[SPEC-0006] Verify presence of mandatory taxonomy prefixes."""
        # SPEC defines: core_, bridge_, util_, v_, compat_
        # We check for these as start of word boundaries in Rust identifiers.
        mandatory_prefixes = ["core_", "bridge_", "v_", "util_", "compat_"]
        found_any = False
        
        # Regex to match prefixes at the start of a Rust identifier (struct, fn, mod, let)
        # e.g. fn core_init, struct bridge_context, let v_runtime
        prefix_regex = r"\b(" + "|".join(mandatory_prefixes) + r")[a-zA-Z0-9_]+"
        
        files_to_check = list(self.src.glob("**/*.rs"))
        
        for f in files_to_check:
            content = f.read_text()
            if re.search(prefix_regex, content):
                found_any = True
                break
            
        self.assertTrue(found_any, "🚨 GOVERNANCE FAIL: No formal taxonomy prefixes (core_, bridge_, v_, etc.) found in src/. SPEC-0006 violation.")

    def test_SPEC_0005_environment_tiers(self):
        """[SPEC-0005] Verify environment tiering (VELO_SYS_, VELO_APP_, etc.)."""
        # SPEC defines: VELO_SYS_*, VELO_CONF_*, VELO_APP_*, VELO_RUNTIME_*
        
        mandatory_tiers = ["VELO_SYS_", "VELO_CONF_", "VELO_APP_", "VELO_RUNTIME_"]
        found_tiers = []
        
        files_to_check = list(self.src.glob("**/*.rs"))
        for tier in mandatory_tiers:
            for f in files_to_check:
                if tier in f.read_text():
                    found_tiers.append(tier)
                    break
        
        missing = set(mandatory_tiers) - set(found_tiers)
        self.assertEqual(len(missing), 0, f"🚨 GOVERNANCE FAIL: Missing mandatory environment tiers: {missing}. SPEC-0005 violation.")

    def test_SPEC_0005_audit_tool_presence(self):
        """[SPEC-0005] Verify 'velo audit' CLI command presence."""
        # The spec says 'velo audit' is the primary enforcement mechanism.
        # We check the USAGE string in cli.rs
        cli_rs = self.src / "cli.rs"
        content = cli_rs.read_text()
        
        self.assertIn("velo audit", content.lower(), "🚨 GOVERNANCE FAIL: 'velo audit' command not found in cli.rs USAGE. SPEC-0005 violation.")

    def test_SOP_004_zero_hardcode_clean_sweep(self):
        """[SOP-004] Verify absence of absolute paths and hardcoded environment toxins."""
        # 1. Check constants.toml for absolute paths (excluding placeholders)
        config_toml = self.root / "config" / "constants.toml"
        if config_toml.exists():
            content = config_toml.read_text()
            # Find lines like 'key = "/abs/path"' but not 'key = "${VAR}/path"'
            # or lines containing specific developer home markers
            toxic_patterns = [
                r'"/Users/[^"]+"',
                r'"/home/[^"]+"',
                r'"/private/var/[^"]+"',
                r'"/tmp/[^"]+"'
            ]
            for pattern in toxic_patterns:
                matches = re.findall(pattern, content)
                self.assertEqual(len(matches), 0, f"🚨 GOVERNANCE FAIL: Hardcoded absolute path '{matches}' found in constants.toml. SOP-004 violation.")

        # 2. Check src/ for static absolute paths in strings
        files_to_check = list(self.src.glob("**/*.rs"))
        # We allow some system paths like /dev/fd or /proc/self/fd, but not home paths or /tmp
        absolute_toxin_regex = r'"/(Users|home|tmp|private)/[^"]+"'
        
        found_toxins = []
        for f in files_to_check:
            content = f.read_text()
            matches = re.findall(absolute_toxin_regex, content)
            if matches:
                found_toxins.append(f"{f.name}: {matches}")
        
        self.assertEqual(len(found_toxins), 0, f"🚨 GOVERNANCE FAIL: Absolute path toxins found in src/: {found_toxins}. SOP-004 violation.")

if __name__ == "__main__":
    unittest.main()
