from __future__ import annotations

"""
Velo QA: Phase 3 Deployment Tests
==================================
GOAL: Expose hardcoded path bugs that only appear in production deployment.

Problem found in find_zygote_module():
- Hardcoded "velo_zygote/main.py" path
- Only searches 4 levels from exe
- WILL FAIL when installed via pip/cargo install
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Import CI-aware timeout constants
from conftest_utils import T_MEDIUM, get_velo_binary


class DeployEnv:
    """Simulate a deployed/installed environment."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="deploy_"))
        self.velo = get_velo_binary()
        self.bin_dir = self.path / "bin"
        self.lib_dir = self.path / "lib"
        # Isolate sockets
        self.socket_dir = self.path / ".sockets"
        self.env_vars = {
            "VELO_SOCKET_DIR": str(self.socket_dir),
            "VELO_ZYGOTE_SOCKET": str(self.socket_dir / "velo-zygote.sock"),
        }
        self.socket_dir.mkdir(exist_ok=True)

    def setup(self):
        # Create typical install structure
        self.bin_dir.mkdir()
        self.lib_dir.mkdir()

        # Create project dir
        self.project_dir = self.path / "project"
        self.project_dir.mkdir()
        subprocess.run(["uv", "venv", "--quiet"], cwd=self.project_dir, capture_output=True)
        (self.project_dir / "uv.lock").write_text("{}")

        return self

    def copy_velo_to_bin(self):
        """Simulate `cargo install` - velo binary is in isolated bin/."""
        dest = self.bin_dir / "velo"
        shutil.copy(self.velo, dest)
        os.chmod(dest, 0o755)
        return str(dest)

    def create_script(self, name, content):
        (self.project_dir / name).write_text(content)

    def run(self, velo_path, args, timeout=None):
        if timeout is None:
            timeout = T_MEDIUM  # CI-aware timeout

        env = os.environ.copy()
        env.update(self.env_vars)

        result = subprocess.run(
            [velo_path] + args, cwd=self.project_dir, capture_output=True, text=True, timeout=timeout, env=env
        )
        return result.returncode, result.stdout, result.stderr

    def cleanup(self):
        # Stop Zygote gracefully via isolated socket
        try:
            env = os.environ.copy()
            env.update(self.env_vars)
            subprocess.run([self.velo, "zygote", "stop"], capture_output=True, timeout=5, env=env)
        except Exception:
            pass

        try:
            shutil.rmtree(self.path)
        except:
            pass

    def __enter__(self):
        return self.setup()

    def __exit__(self, *args):
        self.cleanup()


class TestDeploymentScenarios:
    """Test Zygote in realistic deployment scenarios."""

    def test_deploy_001_isolated_binary(self):
        """
        DEPLOY-001: Velo binary installed in isolated /usr/local/bin.

        This simulates `cargo install velo` where binary goes to ~/.cargo/bin
        but velo_zygote/main.py is NOT copied.
        """
        with DeployEnv() as env:
            # Simulate installed binary (no velo_zygote nearby)
            installed_velo = env.copy_velo_to_bin()

            env.create_script("test.py", 'print("deployed")')

            code, stdout, stderr = env.run(installed_velo, ["run", "--zygote", "test.py"])

            # When binary is isolated without velo_zygote module:
            # 1. Zygote fails to start (expected when module not bundled)
            # 2. Velo falls back to normal mode (graceful degradation)
            # 3. Script still runs successfully

            # Accept EITHER: Zygote works OR graceful fallback
            if "Could not find velo_zygote" in stderr:
                # Module not found - check fallback works
                assert "Falling back" in stderr, (
                    f"DEPLOY-001: No graceful fallback when module missing!\nstderr: {stderr}"
                )
                assert code == 0, f"Fallback failed! code={code}"
            else:
                # Zygote worked - even better
                assert code == 0, f"Zygote mode failed! code={code}"

    def test_deploy_002_deep_nested_project(self):
        """
        DEPLOY-002: Velo binary run from deeply nested project.

        Even with velo_zygote alongside binary, if project is > 4 levels deep,
        find_zygote_module() will fail.
        """
        with DeployEnv() as env:
            # Create deep directory structure
            deep_project = env.path / "a" / "b" / "c" / "d" / "e" / "project"
            deep_project.mkdir(parents=True)

            subprocess.run(["uv", "venv", "--quiet"], cwd=deep_project, capture_output=True)
            (deep_project / "uv.lock").write_text("{}")
            (deep_project / "test.py").write_text('print("deep")')

            result = subprocess.run(
                [env.velo, "run", "--zygote", "test.py"],
                cwd=deep_project,
                capture_output=True,
                text=True,
                timeout=30,
            )

            print(f"  Deep project: {deep_project}")
            print("  Depth from root: 6 levels")
            print(f"  Result: code={result.returncode}")

            if "Could not find velo_zygote" in result.stderr:
                print("  ⚠️ DEPLOY BUG: Depth > 4 breaks module discovery!")

    def test_deploy_003_symlinked_binary(self):
        """
        DEPLOY-003: Velo binary is a symlink.

        Common pattern: /usr/local/bin/velo -> /opt/velo/bin/velo
        current_exe() returns the symlink path, not canonical.
        """
        with DeployEnv() as env:
            installed_velo = env.copy_velo_to_bin()

            # Create symlink to binary
            symlink_path = (
                self.path / "usr_local_bin" / "velo" if hasattr(self, "path") else env.path / "usr_local_bin" / "velo"
            )
            symlink_path.parent.mkdir(parents=True, exist_ok=True)
            symlink_path.symlink_to(installed_velo)

            env.create_script("test.py", 'print("symlinked")')

            code, stdout, stderr = env.run(str(symlink_path), ["run", "--zygote", "test.py"])

            print(f"  Symlink: {symlink_path} -> {installed_velo}")
            print(f"  Result: code={code}")

            if "Could not find velo_zygote" in stderr:
                print("  ⚠️ DEPLOY BUG: Symlinked binary can't find module!")

    def test_deploy_004_readonly_install_dir(self):
        """
        DEPLOY-004: Installed in read-only directory.

        /usr/bin/velo is read-only, can't create cache there.
        """
        with DeployEnv() as env:
            installed_velo = env.copy_velo_to_bin()

            # Make bin dir read-only
            os.chmod(str(env.bin_dir), 0o555)

            env.create_script("test.py", 'print("readonly")')

            try:
                code, stdout, stderr = env.run(installed_velo, ["run", "--zygote", "test.py"])
                print(f"  Result: code={code}")
            finally:
                os.chmod(str(env.bin_dir), 0o755)

    def test_deploy_005_no_velo_zygote_module(self):
        """
        DEPLOY-005: velo_zygote module completely missing.

        User installed only the binary, no Python support files.
        """
        with DeployEnv() as env:
            installed_velo = env.copy_velo_to_bin()

            # Ensure NO velo_zygote anywhere
            # (DeployEnv doesn't copy it, so it's already missing)

            env.create_script("test.py", 'print("no_module")')

            code, stdout, stderr = env.run(installed_velo, ["run", "--zygote", "test.py"])

            # Should fail gracefully with clear error
            assert "velo_zygote" in stderr.lower() or "not found" in stderr.lower() or code == 0, (
                f"Unclear error message! stderr={stderr}"
            )

            # Check if it fell back to non-zygote mode
            if "Falling back" in stderr:
                print("  ✅ Graceful fallback when module missing")
            else:
                print(f"  Error handling: {stderr[:100]}")


class TestEnvironmentVariableFallbacks:
    """Test if there are environment variable fallbacks."""

    def test_env_001_velo_home_not_respected(self):
        """
        ENV-001: VELO_HOME environment variable not used.

        User should be able to set VELO_HOME to point to velo installation.
        """
        with DeployEnv() as env:
            installed_velo = env.copy_velo_to_bin()

            # Create velo_zygote in custom location
            custom_home = env.path / "custom_velo_home"
            custom_zygote = custom_home / "velo_zygote"
            custom_zygote.mkdir(parents=True)

            # Copy actual main.py
            repo_root = Path(__file__).parents[4]
            real_main_py = repo_root / "velo_zygote" / "main.py"
            if real_main_py.exists():
                shutil.copy(real_main_py, custom_zygote / "main.py")
            else:
                (custom_zygote / "main.py").write_text("# placeholder")

            env.create_script("test.py", 'print("env_test")')

            # Run with VELO_HOME set
            result = subprocess.run(
                [installed_velo, "run", "--zygote", "test.py"],
                cwd=env.project_dir,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "VELO_HOME": str(custom_home)},
            )

            # VELO_HOME should be respected!
            # If it's not, Zygote can't find the module even when we tell it where
            assert "Could not find velo_zygote" not in result.stderr, (
                f"ENV-001 BUG: VELO_HOME not respected!\n"
                f"VELO_HOME={custom_home}\n"
                f"Module exists at: {custom_zygote / 'main.py'}\n"
                f"But Zygote still can't find it!\n"
                f"stderr: {result.stderr}"
            )

    def test_env_002_pythonpath_ignored(self):
        """
        ENV-002: PYTHONPATH doesn't help find velo_zygote.

        Because find_zygote_module() uses file system search, not Python imports.
        """
        with DeployEnv() as env:
            installed_velo = env.copy_velo_to_bin()

            # Put velo_zygote somewhere and add to PYTHONPATH
            custom_path = env.path / "custom_lib"
            custom_zygote = custom_path / "velo_zygote"
            custom_zygote.mkdir(parents=True)
            (custom_zygote / "main.py").write_text("# placeholder")
            (custom_zygote / "__init__.py").write_text("")

            env.create_script("test.py", 'print("pythonpath_test")')

            result = subprocess.run(
                [installed_velo, "run", "--zygote", "test.py"],
                cwd=env.project_dir,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "PYTHONPATH": str(custom_path)},
            )

            print(f"  PYTHONPATH={custom_path}")
            print(f"  Result: code={result.returncode}")

            # This won't work because find_zygote_module() doesn't use Python import
            if "Could not find velo_zygote" in result.stderr:
                print("  ℹ️ As expected: PYTHONPATH doesn't help (filesystem search)")


class TestInstallDirectoryStructures:
    """Test various installation directory structures."""

    def test_struct_001_pip_install_structure(self):
        """
        STRUCT-001: Simulate pip install structure.

        pip install velo would put:
        - ~/.local/bin/velo (or entry point script)
        - ~/.local/lib/python3.x/site-packages/velo_zygote/
        """
        with DeployEnv() as env:
            # This is what pip would create
            bin_dir = env.path / ".local" / "bin"
            site_packages = env.path / ".local" / "lib" / "python3.11" / "site-packages"

            bin_dir.mkdir(parents=True)
            site_packages.mkdir(parents=True)

            # Binary in bin
            pip_velo = bin_dir / "velo"
            shutil.copy(env.velo, pip_velo)
            os.chmod(pip_velo, 0o755)

            # Module in site-packages (where pip would put it)
            zygote_pkg = site_packages / "velo_zygote"
            zygote_pkg.mkdir()
            (zygote_pkg / "__init__.py").write_text("")
            (zygote_pkg / "main.py").write_text("# placeholder")

            env.create_script("test.py", 'print("pip_structure")')

            code, stdout, stderr = env.run(str(pip_velo), ["run", "--zygote", "test.py"])

            print(f"  Binary: {pip_velo}")
            print(f"  Module: {zygote_pkg}")
            print("  Distance: many levels apart!")
            # pip install structure MUST be supported
            assert "Could not find velo_zygote" not in stderr, (
                f"STRUCT-001 BUG: pip install structure not supported!\n"
                f"Binary: {pip_velo}\n"
                f"Module: {zygote_pkg}\n"
                f"This is a critical deployment bug.\n"
                f"stderr: {stderr}"
            )

    def test_struct_002_homebrew_structure(self):
        """
        STRUCT-002: Simulate Homebrew install structure.

        brew install velo would put:
        - /opt/homebrew/bin/velo
        - /opt/homebrew/Cellar/velo/1.0.0/libexec/velo_zygote/
        """
        with DeployEnv() as env:
            brew_bin = env.path / "opt" / "homebrew" / "bin"
            brew_cellar = env.path / "opt" / "homebrew" / "Cellar" / "velo" / "1.0.0"

            brew_bin.mkdir(parents=True)
            brew_cellar.mkdir(parents=True)

            # Real binary in Cellar
            real_velo = brew_cellar / "bin" / "velo"
            real_velo.parent.mkdir()
            shutil.copy(env.velo, real_velo)
            os.chmod(real_velo, 0o755)

            # Symlink in /opt/homebrew/bin
            brew_link = brew_bin / "velo"
            brew_link.symlink_to(real_velo)

            # Module in libexec
            lib_zygote = brew_cellar / "libexec" / "velo_zygote"
            lib_zygote.mkdir(parents=True)
            (lib_zygote / "main.py").write_text("# placeholder")

            env.create_script("test.py", 'print("homebrew_structure")')

            code, stdout, stderr = env.run(str(brew_link), ["run", "--zygote", "test.py"])

            print(f"  Symlink: {brew_link}")
            print(f"  Real binary: {real_velo}")
            print(f"  Module: {lib_zygote}")
            # Homebrew structure MUST be supported
            assert "Could not find velo_zygote" not in stderr, (
                f"STRUCT-002 BUG: Homebrew structure not supported!\n"
                f"Symlink: {brew_link}\n"
                f"Real binary: {real_velo}\n"
                f"Module: {lib_zygote}\n"
                f"stderr: {stderr}"
            )
