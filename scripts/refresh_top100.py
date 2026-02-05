#!/usr/bin/env python3
"""
Fetch the top 100 most-downloaded PyPI packages.
Saves the list to benchmarks/top100_list.json.
"""

import json
import subprocess
import sys
from pathlib import Path

# URL for the 30-day top packages JSON
TOP_PACKAGES_URL = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.json"
OUTPUT_PATH = Path(__file__).parent.parent / "tests" / "benchmarks" / "top100_list.json"


def fetch_top_100():
    print(f"🔍 Fetching top packages from {TOP_PACKAGES_URL}...")
    try:
        # Use curl to fetch the data
        result = subprocess.run(["curl", "-s", TOP_PACKAGES_URL], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        # Extract project names
        top_100 = [row["project"] for row in data["rows"][:100]]

        if len(top_100) < 100:
            print(f"⚠️  Warning: Only found {len(top_100)} packages.")

        # Ensure directory exists
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Save to JSON
        with open(OUTPUT_PATH, "w") as f:
            json.dump(
                {"date": data.get("last_update", "unknown"), "packages": top_100},
                f,
                indent=2,
            )

        print(f"✅ Successfully saved {len(top_100)} packages to {OUTPUT_PATH}")
        return top_100

    except Exception as e:
        print(f"❌ Error fetching packages: {e}")
        sys.exit(1)


if __name__ == "__main__":
    fetch_top_100()
