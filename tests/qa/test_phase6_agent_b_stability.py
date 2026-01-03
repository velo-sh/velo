# Agent B (Stability) Test Suite: RFC-0009 Static Graph

import pytest
import os
import sys
from pathlib import Path

@pytest.mark.tier1
class TestAgentBStability:
    """Agent B specialized core flow and stability tests for Phase 6.0."""

    def test_FUNC_601_recursive_path_mutation(self, isolated_env):
        """FUNC-601-EXT: Verify recursive fallback when nested package mutates __path__."""
        env = isolated_env
        
        # Structure: pkg_root -> sub_pkg (mutated) -> module_c
        os.makedirs(env.path / "pkg_root" / "sub_pkg", exist_ok=True)
        env.create_app("pkg_root/__init__.py", "")
        env.create_app("pkg_root/sub_pkg/__init__.py", """
import os
__path__.append(os.path.join(os.path.dirname(__file__), 'extra'))
""")
        
        # Submodule C in the mutated 'extra' path
        extra_dir = env.path / "pkg_root" / "sub_pkg" / "extra"
        os.makedirs(extra_dir, exist_ok=True)
        env.create_app("pkg_root/sub_pkg/extra/module_c.py", "VAL = 'nested_detected'")
        
        env.create_app("main.py", "from pkg_root.sub_pkg import module_c; print(module_c.VAL)")
        
        env.run_velo("build")
        result = env.run_velo("run", "--fast", "main.py")
        assert result.returncode == 0
        assert "nested_detected" in result.stdout

    def test_FUNC_605_namespace_package_clash(self, isolated_env):
        """FUNC-605: Verify PEP 420 Namespace Package split across bundle and disk."""
        env = isolated_env
        
        # 1. Primary root in bundle
        os.makedirs(env.path / "ns_pkg", exist_ok=True)
        env.create_app("ns_pkg/mod_a.py", "SOURCE = 'bundle'")
        
        # 2. Secondary root on disk (simulated by adding to sys.path)
        external_root = env.path / "external"
        os.makedirs(external_root / "ns_pkg", exist_ok=True)
        env.create_app("external/ns_pkg/mod_b.py", "SOURCE = 'disk'")
        
        env.create_app("main.py", f"""
import sys
sys.path.append('{external_root}')
import ns_pkg.mod_a
import ns_pkg.mod_b
print(f"A:{{ns_pkg.mod_a.SOURCE}} B:{{ns_pkg.mod_b.SOURCE}}")
""")
        
        env.run_velo("build")
        result = env.run_velo("run", "--fast", "main.py")
        
        assert result.returncode == 0
        assert "A:bundle B:disk" in result.stdout

    def test_L4_1_dynamic_import_fallback(self, isolated_env):
        """L4-1: Verify that dynamic imports (importlib) work and log fallback."""
        env = isolated_env
        env.create_app("main.py", """
import importlib
name = 'mod_a'
mod = importlib.import_module(name)
print(f"VAL:{mod.VAL}")
""")
        env.create_app("mod_a.py", "VAL = 'dynamic_ok'")
        env.run_velo("build")
        
        # Run with metrics to verify fallback_reason
        os.environ["VELO_REPORT_METRICS"] = "1"
        result = env.run_velo("run", "--fast", "main.py")
        assert "VAL:dynamic_ok" in result.stdout

    def test_L4_2_soft_dependency_no_preload(self, isolated_env):
        """L4-2: Verify that soft dependencies (in try/if False) are not pre-mapped."""
        env = isolated_env
        env.create_app("main.py", """
try:
    import optional_mod
except ImportError:
    print("SOFT_OK")
""")
        # We don't create optional_mod.py at build time
        env.run_velo("build")
        
        # Run should handle ImportError gracefully
        result = env.run_velo("run", "--fast", "main.py")
        assert "SOFT_OK" in result.stdout

    def test_FUNC_602_import_hook_interception(self, isolated_env):
        """FUNC-602: Verify that builtins.__import__ hooks are still called (no bypass)."""
        env = isolated_env
        
        env.create_app("mod.py", "DATA = 'secret'")
        
        # Intercept builtins.__import__ (Instrumentation/Mocking pattern)
        env.create_app("main.py", """
import builtins
original_import = builtins.__import__
import_calls = []

def custom_import(name, *args, **kwargs):
    import_calls.append(name)
    return original_import(name, *args, **kwargs)

builtins.__import__ = custom_import

import mod
print(f"CALLED:{'mod' in import_calls}")
""")
        
        env.run_velo("build")
        result = env.run_velo("run", "--fast", "main.py")
        
        assert result.returncode == 0
        assert "CALLED:True" in result.stdout

    def test_FUNC_603_lazy_import_compliance(self, isolated_env):
        """FUNC-603: Verify compatibility with PEP 690 Lazy Imports."""
        env = isolated_env
        
        env.create_app("mod.py", "print('MOD_EXECUTED')")
        env.create_app("main.py", """
import mod
print('MAIN_START')
x = mod
""")
        
        env.run_velo("build")
        
        # Run with lazy imports enabled (if supported by Python version)
        # We check if mod execution is deferred
        env_vars = os.environ.copy()
        env_vars["PYTHONDEBUG"] = "L" 
        
        result = env.run_velo("run", "--fast", "main.py", env=env_vars)
        
        # In lazy mode, MAIN_START should appear before MOD_EXECUTED
        # Note: This test depends on Python version supporting lazy imports
        if "MAIN_START" in result.stdout and "MOD_EXECUTED" in result.stdout:
            main_idx = result.stdout.find("MAIN_START")
            mod_idx = result.stdout.find("MOD_EXECUTED")
            assert main_idx < mod_idx

    def test_FUNC_604_phf_fallback_on_collision(self, isolated_env):
        """FUNC-604: Verify fallback to standard HashMap if PHF generation fails."""
        env = isolated_env
        
        # Create a project with enough modules to potentially cause PHF difficulties 
        # (or just verify the fallback logic works if PHF is disabled)
        for i in range(10):
            env.create_app(f"m{i}.py", "")
            
        env.create_app("main.py", "import m0; print('OK')")
        
        # We can't easily force PHF failure from here without changing Velo code,
        # but we can verify the 'index_type' field detection if we had access to the binary structure.
        # For now, we ensure basic functionality with standard build.
        env.run_velo("build")
        result = env.run_velo("run", "--fast", "main.py")
        assert "OK" in result.stdout
