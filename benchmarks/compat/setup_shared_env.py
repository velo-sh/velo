#!/usr/bin/env python3
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
BENCHMARKS_DIR = ROOT_DIR / "benchmarks" / "compat"
SHARED_VENV_DIR = BENCHMARKS_DIR / ".shared_venv"
REQUIREMENTS_FILE = BENCHMARKS_DIR / "requirements-all.txt"
BASE_REQS = ["pytest", "pytest-json-report", "tomli", "uv"]


def run_cmd(cmd, cwd=None):
    print(f"👉 {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)


def main():
    if "--clean" in sys.argv:
        if SHARED_VENV_DIR.exists():
            print(f"🗑️  Removing existing venv: {SHARED_VENV_DIR}")
            shutil.rmtree(SHARED_VENV_DIR)

    if not SHARED_VENV_DIR.exists():
        print(f"📦 Creating Shared Venv at {SHARED_VENV_DIR}")
        run_cmd(["uv", "venv", str(SHARED_VENV_DIR)])
    else:
        print(f"✅ Shared Venv exists at {SHARED_VENV_DIR}")

    if not REQUIREMENTS_FILE.exists():
        print("❌ requirements-all.txt not found! Please generate it first.")
        # Fallback generation
        print("🔄 Generating requirements list...")
        pkgs = set()
        for p in BENCHMARKS_DIR.glob("*/*/compat.toml"):
            pkgs.add(p.parent.name)

        with open(REQUIREMENTS_FILE, "w") as f:
            for pkg in sorted(pkgs):
                f.write(f"{pkg}\n")
        print(f"📄 Generated {REQUIREMENTS_FILE} with {len(pkgs)} packages.")

    venv_python = SHARED_VENV_DIR / "bin" / "python"
    print("🚀 Installing base requirements...")
    run_cmd(["uv", "pip", "install", *BASE_REQS, "--python", str(venv_python)])

    print("🚀 Installing all packages into Shared Venv (this may take a while)...")

    # Use uv pip install with the shared venv explicitly
    run_cmd(
        [
            "uv",
            "pip",
            "install",
            "-r",
            str(REQUIREMENTS_FILE),
            "--python",
            str(venv_python),
        ]
    )

    print("\n✅ Shared Environment Setup Complete!")
    print(f"   Path: {SHARED_VENV_DIR}")
    print(f"   Python: {venv_python}")


if __name__ == "__main__":
    main()

# [FIX] Uninstall argparse as it breaks Python 3.11+
print("   🧹 Ensuring no 'argparse' package shadows stdlib...")
subprocess.run(
    ["uv", "pip", "uninstall", "argparse", "--python", str(SHARED_VENV_DIR)], check=False, capture_output=True
)
