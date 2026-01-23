import re
import sys
from pathlib import Path

# SOP-005: Governance Enforcement Script
# This script is the "Institutionalized" gatekeeper for Velo's architectural standards.
# FAILURE = HARD REJECT


class VeloEnforcer:
    def __init__(self) -> None:
        self.root = Path(__file__).parent.parent.parent
        self.src = self.root / "src"
        self.config = self.root / "config"
        self.errors: list[str] = []

    def log_error(self, message: str) -> None:
        print(f"❌ [ENFORCEMENT FAILURE]: {message}")
        self.errors.append(message)

    def check_zhc(self) -> None:
        """[SOP-004] Zero-Hardcode Enforcement."""
        toxic_patterns = [
            (r'"/Users/[^"]+"', "Hardcoded Developer Home"),
            (r'"/home/[^"]+"', "Hardcoded Linux Home"),
            (r'"/tmp/[^"]+"', "Hardcoded /tmp (Use std::env::temp_dir)"),
            (r'"/private/var/[^"]+"', "Hardcoded macOS Var Path"),
        ]

        # Check src/ for string toxins
        for f in self.src.glob("**/*.rs"):
            content = f.read_text()
            for pattern, reason in toxic_patterns:
                if re.search(pattern, content):
                    self.log_error(f"{f.relative_to(self.root)}: {reason}")

        # Check config/constants.toml
        constants_toml = self.config / "constants.toml"
        if constants_toml.exists():
            content = constants_toml.read_text()
            for pattern, reason in toxic_patterns:
                if re.search(pattern, content):
                    self.log_error(f"config/constants.toml: {reason}")

    def check_taxonomy(self) -> None:
        """[SPEC-0006] Naming Taxonomy Enforcement."""
        mandatory_prefixes = ["core_", "bridge_", "v_", "util_", "compat_"]
        prefix_regex = r"\b(" + "|".join(mandatory_prefixes) + r")[a-zA-Z0-9_]+"

        found_any = False
        for f in self.src.glob("**/*.rs"):
            if re.search(prefix_regex, f.read_text()):
                found_any = True
                break

        if not found_any:
            self.log_error(
                "No mandatory taxonomy prefixes (core_, bridge_, etc.) found in src/. Naming convention violation."
            )

    def run(self) -> None:
        print("🚀 Starting Velo Governance Enforcement (SOP-005)...")
        self.check_zhc()
        self.check_taxonomy()

        if self.errors:
            print(f"\n🛑 [TOTAL FAILURES: {len(self.errors)}] - REJECTED")
            sys.exit(1)
        else:
            print("\n✅ [GOVERNANCE CLEAN] - PASS")
            sys.exit(0)


if __name__ == "__main__":
    VeloEnforcer().run()
