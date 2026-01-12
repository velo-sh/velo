import os
import subprocess
from pathlib import Path


def setup_project():
    project_dir = Path("test_large_bundle")
    project_dir.mkdir(exist_ok=True)

    # Create a large script (300MB)
    script_path = project_dir / "large_script.py"

    # Copy velo_loader.py into project dir to ensure we test the edited version
    import shutil

    shutil.copy("python/velo_loader.py", project_dir / "velo_loader.py")

    with open(script_path, "w") as f:
        f.write("import sys\n")
        f.write("print('Hello from large script')\n")
        # Add 300MB of comments
        f.write("#" * (300 * 1024 * 1024))

    return project_dir, script_path


def build_bundle(project_dir):
    # Use bundle_builder.py to create bundle
    subprocess.run(
        ["python3", "python/bundle_builder.py", str(project_dir)], check=True
    )
    bundle_path = project_dir / "bundle.veloc"

    # Append padding to make it truly large (e.g., 300MB)
    # The size check happens before hash verification, so this is fine for Step 2.
    # For Step 3, we need to make sure the loader doesn't fail on hash if possible,
    # but the current loader hashes up to index_offset, so appending data AFTER
    # index_offset won't affect the hash!
    with open(bundle_path, "ab") as f:
        f.write(b"\0" * (300 * 1024 * 1024))

    print(
        f"Bundle created at {bundle_path}, size: {bundle_path.stat().st_size / 1024 / 1024:.2f} MB"
    )
    return bundle_path


def run_velo_fast(project_dir, script_path, env=None):
    result = subprocess.run(
        ["./target/release/velo", "run", "--fast", str(script_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    return result


def main():
    project_dir, script_path = setup_project()
    try:
        # 1. Build bundle
        bundle_path = build_bundle(project_dir)

        # 2. Try without config (default limit applies)
        config_path = project_dir / "pyproject.toml"
        with open(config_path, "w") as f:
            f.write("[project]\nname = 'test-bundle'\n")

        print("\nStep 2: Testing with default limit (256MB)...")
        res = run_velo_fast(project_dir, script_path)
        print(f"Exit code: {res.returncode}")
        print(f"Stdout: {res.stdout}")
        print(f"Stderr: {res.stderr}")

        # In this world, fast loader fails but falls back, so exit code is 0
        if "Bundle too large" in res.stdout and "268435456" in res.stdout:
            print("✅ Successfully rejected oversized bundle with default limit.")
        else:
            print("❌ Failed to reject oversized bundle with default limit.")

        # 3. Add override config (400MB)
        print("\nStep 3: Testing with max_bundle_size = 400 override...")
        with open(config_path, "w") as f:
            f.write("[tool.velo]\n")
            f.write("max_bundle_size = 400\n")

        res = run_velo_fast(project_dir, script_path)
        print(f"Exit code: {res.returncode}")
        print(f"Stdout: {res.stdout}")
        print(f"Stderr: {res.stderr}")

        if res.returncode == 0 and "Hello from large script" in res.stdout:
            print("✅ Successfully ran with custom bundle size limit.")
        else:
            print("❌ Failed to run even with custom bundle size limit.")

    finally:
        # Cleanup
        # os.remove(script_path)
        # os.remove(bundle_path)
        # os.remove(project_dir / "pyproject.toml")
        # project_dir.rmdir()
        pass


if __name__ == "__main__":
    main()
