#!/usr/bin/env python3
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
BENCHMARKS_DIR = ROOT_DIR / "benchmarks" / "top100"
SHARED_VENV_DIR = BENCHMARKS_DIR / ".shared_venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements-all.txt"


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
        for p in BENCHMARKS_DIR.glob("*/*/benchmark.toml"):
            pkgs.add(p.parent.name)

        with open(REQUIREMENTS_FILE, "w") as f:
            for pkg in sorted(pkgs):
                f.write(f"{pkg}\n")
        print(f"📄 Generated {REQUIREMENTS_FILE} with {len(pkgs)} packages.")

    print("🚀 Installing all packages into Shared Venv (this may take a while)...")

    # Use uv pip install with the shared venv explicitly
    # Note: uv respects VIRTUAL_ENV env var or --python arg
    # We use --python to point to the venv python
    venv_python = SHARED_VENV_DIR / "bin" / "python"

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
