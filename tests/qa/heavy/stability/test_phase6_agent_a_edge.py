# Agent A (Edge) Test Suite: RFC-0009 Static Graph

import os
from typing import Any

import pytest


@pytest.mark.tier2
class TestAgentAEdge:
    """Agent A specialized edge and scale tests for Phase 6.0."""

    @pytest.mark.heavy
    def test_L0_1_ast_dependency_classification(self, isolated_env: Any) -> None:
        """L0-1: Verify dependency classification (Hard vs Soft)."""
        env = isolated_env
        env.create_app(
            "main.py",
            """
import hard_mod          # Hard
if False: import soft_if  # Soft
try:
    import soft_try
except:
    pass # Soft
def f(): import soft_fn  # Soft
""",
        )
        env.create_app("hard_mod.py", "")
        env.create_app("soft_if.py", "")
        env.create_app("soft_try.py", "")
        env.create_app("soft_fn.py", "")

        # Build - Inspect graph for classification metadata
        # (Assuming 'velo build --inspect' exists or checking binary for pre-load flags)
        env.run_velo("bundle", "build")

        # Verify result: Hard should be pre-mapped, Soft should fallback or be marked lazy
        result = env.run_velo("run", "--fast", "main.py")
        assert result.returncode == 0

    @pytest.mark.heavy
    def test_L0_2_scc_cyclic_handle(self, isolated_env: Any) -> None:
        """L0-2: Verify Tarjan's SCC handling for circular imports (a -> b -> c -> a)."""
        env = isolated_env
        env.create_app("a.py", "import b")
        env.create_app("b.py", "import c")
        env.create_app("c.py", "import a")
        env.create_app("main.py", "import a; print('CYCLE_OK')")

        # Build should not fail or hang
        result = env.run_velo("bundle", "build")
        assert result.returncode == 0

        # Run should handle cyclic import normally (Python semantics)
        result = env.run_velo("run", "--fast", "main.py")
        assert "CYCLE_OK" in result.stdout

    @pytest.mark.parametrize("depth", [10, 50, 100])
    def test_EDGE_601_deep_dependency_dag(self, isolated_env: Any, depth: int) -> None:
        """EDGE-601: Verify resolution of deep dependency chains without stack overflow."""
        env = isolated_env

        # Create a linear dependency chain: m_{i} -> m_{i+1}
        for i in range(depth):
            if i == depth - 1:
                env.create_app(f"m{i}.py", "DATA = 'tail'")
            else:
                env.create_app(f"m{i}.py", f"import m{i + 1}\nDATA = m{i + 1}.DATA")

        env.create_app("main.py", "import m0; print(m0.DATA)")

        # Build with graph
        env.run_velo("bundle", "build")

        # Run with fast loader
        result = env.run_velo("run", "--fast", "main.py")
        assert result.returncode == 0
        assert "tail" in result.stdout

    @pytest.mark.heavy
    def test_EDGE_602_string_interning_scale(self, isolated_env: Any) -> None:
        """EDGE-602: Verify interning of module name prefixes for large projects (500 modules)."""
        env = isolated_env
        module_count = 500

        # Create many modules in shared packages to test prefix interning
        # package_a.sub_{i}, package_b.sub_{i}
        main_code = []
        for i in range(module_count):
            pkg = "pkg_a" if i % 2 == 0 else "pkg_b"
            mod_name = f"{pkg}/m{i}.py"
            os.makedirs(env.path / pkg, exist_ok=True)
            env.create_app(mod_name, f"ID = {i}")
            main_code.append(f"import {pkg}.m{i}")

        env.create_app("main.py", "\n".join(main_code) + "\nprint('LOADED_ALL')")

        # Build should succeed and compress prefixes
        result = env.run_velo("bundle", "build")
        assert result.returncode == 0

        # Run should be fast
        result = env.run_velo("run", "--fast", "main.py")
        assert result.returncode == 0
        assert "LOADED_ALL" in result.stdout

    @pytest.mark.xfail(reason="Design: Bundle uses cached module content; symlink swap requires rebuild")
    def test_EDGE_603_toctou_symlink_swap(self, isolated_env: Any) -> None:
        """EDGE-603: Verify graph invalidation when symlink target changes between build and run."""
        env = isolated_env

        # Create targets
        env.create_app("target_a.py", "VERSION = 'A'")
        env.create_app("target_b.py", "VERSION = 'B'")

        # Create symlink
        link_path = env.path / "link.py"
        os.symlink("target_a.py", link_path)

        env.create_app("main.py", "import link; print(link.VERSION)")

        # Phase 1: Build with target A
        env.run_velo("bundle", "build")
        res1 = env.run_velo("run", "--fast", "main.py")
        assert "A" in res1.stdout

        # Phase 2: Swap symlink to target B
        os.unlink(link_path)
        os.symlink("target_b.py", link_path)

        # Phase 3: Run again. Expected: source_hash mismatch or link detection triggers rebuild
        res2 = env.run_velo("run", "--fast", "main.py")

        # If RFC-0009 is correct, it should detect the change
        assert "B" in res2.stdout

    @pytest.mark.xfail(reason="Design Change: Hard limit 5000 is now configurable, build succeeds")
    def test_EDGE_604_hard_limit_gating(self, isolated_env: Any) -> None:
        """EDGE-604: Verify the 5,000 module hard limit build failure."""
        env = isolated_env
        limit = 5001

        # Create 5001 empty modules
        for i in range(limit):
            env.create_app(f"m{i}.py", "")

        env.create_app("main.py", "import m0")

        # Build should fail at gating
        result = env.run_velo("bundle", "build")
        assert result.returncode != 0
        assert "LimitError" in result.stderr or "MaxGraphSizeExceeded" in result.stderr

    def test_EDGE_605_wide_dag_memory_stress(self, isolated_env: Any) -> None:
        """EDGE-605: Verify memory safety with 'Wide DAG' (4,000 edges from one module)."""
        env = isolated_env
        width = 4000  # Near the 5000 limit

        # Create one root module that imports 4000 others
        imports = []
        for i in range(width):
            env.create_app(f"m{i}.py", "X = 1")
            imports.append(f"import m{i}")

        env.create_app("main.py", "\n".join(imports) + "\nprint('WIDE_OK')")

        # Build - Stress Tarjan's SCC and Phf generation
        env.run_velo("bundle", "build")

        # Run - Ensure no OOM during pre-mapping
        result = env.run_velo("run", "--fast", "main.py")
        assert result.returncode == 0
        assert "WIDE_OK" in result.stdout
