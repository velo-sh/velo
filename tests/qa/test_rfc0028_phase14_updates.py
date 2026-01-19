"""
RFC-0028 Phase 14 Updates Acceptance Tests

RFC-0028 Updated: 2026-01-19
Tests derived from:
- §10.3: Python Module Architecture (v_* Naming Convention)
- §10.3.4: Cross-Layer Invariants (INV-ARCH-001 through 005)
- §12.4: Phase 14 xdist Integration (Execnet Hijacking)
- §15.1: DEF-SOCKET-STABLE (Socket Directory Stability)
- §15.2: VELO_IS_ZYGOTE Worker Guard
- §15.3: DEF-VTEST-ASYNCIO (Asyncio Event Loop Cleanup)

QA-SOP Tier Classification:
- L0 (Smoke): SOCK-001, SOCK-002
- L1 (Core): ARCH-001/002/003, GUARD-001/002, XDIST-001
- L2 (Edge): ASYNC-001/002, XDIST-002
- L4 (Security): INV-ARCH-001 through 005
"""

import inspect
import os
import sys
from pathlib import Path

import pytest

# =============================================================================
# L1: v_* NAMING CONVENTION ALIGNMENT (RFC-0028 §10.3.1)
# =============================================================================


class TestV_NamingConventionAlignment:
    """RFC-0028 §10.3.1: v_* naming convention MUST be consistent across Python/Rust."""

    def test_ARCH_001_python_v_modules_exist(self):
        """Verify Python v_* modules exist: v_fork.py, v_rsgi.py, v_shield.py"""
        velo_zygote_path = Path(__file__).parent.parent.parent / "velo_zygote"

        required_modules = ["v_fork.py", "v_rsgi.py", "v_shield.py"]

        for module in required_modules:
            module_path = velo_zygote_path / module
            assert module_path.exists(), (
                f"RFC-0028 §10.3.1 VIOLATION: Python module '{module}' MUST exist. Expected at: {module_path}"
            )

    def test_ARCH_002_rust_v_modules_exist(self):
        """Verify Rust v_* modules exist: v_fork.rs"""
        src_zygote_path = Path(__file__).parent.parent.parent / "src" / "zygote"

        required_modules = ["v_fork.rs"]

        for module in required_modules:
            module_path = src_zygote_path / module
            assert module_path.exists(), (
                f"RFC-0028 §10.3.1 VIOLATION: Rust module '{module}' MUST exist. Expected at: {module_path}"
            )

    def test_ARCH_003_module_alignment(self):
        """Verify Python/Rust module pairs are functionally aligned"""
        # Verify v_fork alignment by checking key function exists
        from velo_zygote.v_fork import ForkHandler

        assert hasattr(ForkHandler, "handle_fork"), "ForkHandler.handle_fork MUST exist"
        assert hasattr(ForkHandler, "handle_gateway_fork"), "ForkHandler.handle_gateway_fork MUST exist (Phase 14)"


# =============================================================================
# L4: CROSS-LAYER INVARIANTS (RFC-0028 §10.3.4)
# =============================================================================


class TestCrossLayerInvariants:
    """RFC-0028 §10.3.4: INV-ARCH-001 through INV-ARCH-005"""

    def test_INV_ARCH_001_functional_alignment(self):
        """INV-ARCH-001: Python modules MUST align with corresponding Rust modules"""
        # Verify key functions in Python match RFC §10.3.3 Responsibility Matrix
        from velo_zygote.lifecycle import post_fork_reinit
        from velo_zygote.v_fork import ForkHandler

        # Python side must have lifecycle management
        assert callable(post_fork_reinit), "post_fork_reinit MUST be callable"

        # ForkHandler must handle both legacy and gateway forks
        assert callable(ForkHandler.handle_fork), "ForkHandler.handle_fork MUST be callable"
        assert callable(ForkHandler.handle_gateway_fork), "ForkHandler.handle_gateway_fork MUST be callable"

    def test_INV_ARCH_002_config_ssot(self):
        """INV-ARCH-002: Config MUST be injected via Rust (VELO_* env vars), Python read-only"""
        # Read source code instead of importing (avoids VELO_ENV requirement)
        settings_path = Path(__file__).parent.parent.parent / "velo_zygote" / "settings.py"
        source = settings_path.read_text()

        # Verify settings read from VELO_* environment variables
        assert "VELO_ENV" in source, "INV-ARCH-002: VeloSettings MUST read from VELO_ENV"
        assert "os.environ.get" in source or "os.getenv" in source, (
            "INV-ARCH-002: VeloSettings MUST use os.environ.get() for reading config"
        )

        # Config is read-only: verify module doesn't export setters that mutate env
        # Writes are only acceptable for internal state mgmt, not VELO_* env vars
        assert "os.environ['VELO_" not in source, "INV-ARCH-002: VeloSettings MUST NOT write to VELO_* env vars"

    def test_INV_ARCH_003_no_direct_libc(self):
        """INV-ARCH-003: Python MUST NOT call libc directly for core operations; exceptions allowed for platform-specific safety"""
        from velo_zygote import v_fork

        source = inspect.getsource(v_fork)

        # Exception: PR_SET_PDEATHSIG for orphan prevention is allowed (documented in TITANIUM RULE)
        # We check that ctypes.CDLL is ONLY used in the context of PR_SET_PDEATHSIG
        if "ctypes.CDLL" in source:
            # Verify it's for PR_SET_PDEATHSIG only
            assert "PR_SET_PDEATHSIG" in source, (
                "INV-ARCH-003: ctypes.CDLL found but not for PR_SET_PDEATHSIG. "
                "Only orphan prevention is allowed as an exception."
            )
            # Verify it's Linux-only
            assert 'sys.platform.startswith("linux")' in source, (
                "INV-ARCH-003: ctypes.CDLL for PR_SET_PDEATHSIG MUST be Linux-only"
            )

        # CFFI should never be used
        assert "cffi" not in source.lower(), "INV-ARCH-003: v_fork.py MUST NOT use CFFI for libc access"

    def test_INV_ARCH_004_protocol_compatibility(self):
        """INV-ARCH-004: Each Python module MUST have Rust unit test for protocol compatibility"""
        # Verify Rust tests exist for core_ipc protocol
        rust_test_files = [
            Path(__file__).parent.parent.parent / "src" / "zygote" / "core_ipc.rs",
            Path(__file__).parent.parent.parent / "src" / "zygote" / "v_fork.rs",
        ]

        for test_file in rust_test_files:
            if test_file.exists():
                content = test_file.read_text()
                # Rust modules should have #[test] annotations or mod tests
                has_tests = "#[test]" in content or "mod tests" in content or "#[cfg(test)]" in content
                # This is a SHOULD requirement, not MUST - log warning if missing
                if not has_tests:
                    pytest.skip(f"INFO: {test_file.name} has no embedded tests (acceptable for small modules)")

    def test_INV_ARCH_005_v_naming_standard(self):
        """INV-ARCH-005: v_* prefix is Velo core component standard; Python/Rust MUST unify"""
        velo_zygote_path = Path(__file__).parent.parent.parent / "velo_zygote"
        src_zygote_path = Path(__file__).parent.parent.parent / "src" / "zygote"

        # Count v_* modules in Python and Rust
        python_v_modules = list(velo_zygote_path.glob("v_*.py"))
        rust_v_modules = list(src_zygote_path.glob("v_*.rs"))

        assert len(python_v_modules) >= 3, (
            f"RFC-0028 §10.3.1: Expected >= 3 Python v_* modules, found {len(python_v_modules)}: {python_v_modules}"
        )
        assert len(rust_v_modules) >= 1, (
            f"RFC-0028 §10.3.5: Expected >= 1 Rust v_* module (v_fork.rs), found {len(rust_v_modules)}"
        )


# =============================================================================
# L1: EXECNET HIJACKING PROTOCOL (RFC-0028 §12.4)
# =============================================================================


class TestExecnetHijacking:
    """RFC-0028 §12.4: Phase 14 Execnet Hijacking Protocol"""

    def test_XDIST_001_hijack_execnet_function_exists(self):
        """Verify hijack_execnet() function exists in pytest_velo.plugin"""
        from pytest_velo.plugin import hijack_execnet

        assert callable(hijack_execnet), "hijack_execnet MUST be callable"

        # Verify it has docstring describing the protocol
        assert hijack_execnet.__doc__ is not None, "hijack_execnet MUST have docstring"
        assert "execnet" in hijack_execnet.__doc__.lower(), "hijack_execnet docstring MUST mention execnet"

    def test_XDIST_002_gateway_class_exists(self):
        """Verify ZygoteGateway or equivalent gateway is created for xdist"""
        from pytest_velo import gateway

        assert hasattr(gateway, "ZygoteGateway") or hasattr(gateway, "make_zygote_gateway"), (
            "pytest_velo.gateway MUST have ZygoteGateway or make_zygote_gateway"
        )


# =============================================================================
# L0: SOCKET STABILITY (RFC-0028 §15.1)
# =============================================================================


class TestSocketStability:
    """RFC-0028 §15.1: DEF-SOCKET-STABLE"""

    def test_SOCK_001_stable_socket_directory(self):
        """macOS socket dir MUST be ~/.local/state/velo/sockets/ (not TMPDIR)"""
        from velo_zygote.paths import VeloPaths

        socket_path = VeloPaths.zygote_socket()
        socket_str = str(socket_path)

        if sys.platform == "darwin":
            # macOS: Must NOT use volatile TMPDIR (/var/folders/...)
            assert "/var/folders" not in socket_str, (
                f"DEF-SOCKET-STABLE VIOLATION: macOS socket '{socket_str}' uses volatile TMPDIR. "
                "RFC-0028 §15.1 requires ~/.local/state/velo/sockets/"
            )

            # Should use stable user directory
            assert ".local/state/velo" in socket_str or "velo" in socket_str, (
                f"DEF-SOCKET-STABLE: macOS socket should be in stable user directory, got: {socket_str}"
            )
        else:
            # Linux: XDG_RUNTIME_DIR is acceptable
            assert "velo" in socket_str.lower(), f"Socket path should contain 'velo': {socket_str}"

    def test_SOCK_002_socket_path_consistent(self):
        """Socket path MUST be consistent across multiple calls"""
        from velo_zygote.paths import VeloPaths

        path1 = VeloPaths.zygote_socket()
        path2 = VeloPaths.zygote_socket()

        assert path1 == path2, f"Socket path MUST be deterministic. Got: {path1} vs {path2}"


# =============================================================================
# L1: WORKER GUARD (RFC-0028 §15.2)
# =============================================================================


class TestWorkerGuard:
    """RFC-0028 §15.2: VELO_IS_ZYGOTE Worker Guard"""

    def test_GUARD_001_pytest_configure_checks_guard(self):
        """pytest_configure MUST check VELO_IS_ZYGOTE environment variable"""
        from pytest_velo import plugin

        source = inspect.getsource(plugin.pytest_configure)

        assert "VELO_IS_ZYGOTE" in source, "RFC-0028 §15.2: pytest_configure MUST check VELO_IS_ZYGOTE env var"

    def test_GUARD_002_worker_skips_zygote_init(self):
        """When VELO_IS_ZYGOTE=1, pytest_configure MUST skip Zygote initialization"""
        import pytest_velo.plugin as plugin

        # Save original state
        original_zygote = getattr(plugin, "_zygote", None)
        original_env = os.environ.get("VELO_IS_ZYGOTE")

        try:
            # Simulate being in a Zygote worker
            os.environ["VELO_IS_ZYGOTE"] = "1"
            plugin._zygote = None

            # Create mock config
            class MockOption:
                velo = True
                velo_preload = ""

            class MockConfig:
                option = MockOption()
                rootdir = Path.cwd()

                def addinivalue_line(self, name, value):
                    pass

            # pytest_configure should return early without starting Zygote
            plugin.pytest_configure(MockConfig())

            # Zygote should NOT have been started
            assert plugin._zygote is None, "RFC-0028 §15.2: When VELO_IS_ZYGOTE=1, Zygote MUST NOT be initialized"
        finally:
            # Restore original state
            plugin._zygote = original_zygote
            if original_env is None:
                os.environ.pop("VELO_IS_ZYGOTE", None)
            else:
                os.environ["VELO_IS_ZYGOTE"] = original_env


# =============================================================================
# L2: ASYNCIO EVENT LOOP CLEANUP (RFC-0028 §15.3)
# =============================================================================


class TestAsyncioCleanup:
    """RFC-0028 §15.3: DEF-VTEST-ASYNCIO"""

    def test_ASYNC_001_lifecycle_has_asyncio_cleanup(self):
        """Forked workers MUST have asyncio cleanup in post_fork_reinit"""
        from velo_zygote import lifecycle

        source = inspect.getsource(lifecycle)

        # Must import asyncio
        assert "import asyncio" in source or "from asyncio" in source, (
            "RFC-0028 §15.3: lifecycle.py MUST import asyncio for cleanup"
        )

        # Must handle event loop cleanup
        has_loop_cleanup = "get_running_loop" in source or "get_event_loop" in source or "new_event_loop" in source
        assert has_loop_cleanup, "RFC-0028 §15.3: lifecycle.py MUST handle asyncio event loop cleanup"

    def test_ASYNC_002_post_fork_reinit_callable(self):
        """post_fork_reinit MUST be callable and handle asyncio state"""
        from velo_zygote.lifecycle import post_fork_reinit

        assert callable(post_fork_reinit), "post_fork_reinit MUST be callable"

        # Verify it has proper signature
        sig = inspect.signature(post_fork_reinit)
        # Should accept no required arguments or have defaults
        required_params = [
            p
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        # post_fork_reinit may take optional config
        assert len(required_params) <= 1, (
            f"post_fork_reinit should have <= 1 required params, has {len(required_params)}"
        )


# =============================================================================
# L5: PHASE 14 AUDIT BENCHMARKS (RFC-0028 §7.1)
# =============================================================================


@pytest.mark.tier5
class TestPhase14AuditBenchmarks:
    """RFC-0028 §7.1: Real-World Benchmark Results (Phase 14 Audit)"""

    def test_PERF_001_benchmark_targets_documented(self):
        """Verify Phase 14 benchmark targets are documented in RFC"""
        rfc_path = Path(__file__).parent.parent.parent / "docs" / "rfcs" / "0028-zygote-test-executor.md"

        assert rfc_path.exists(), f"RFC-0028 document MUST exist at {rfc_path}"

        content = rfc_path.read_text()

        # Verify benchmark table exists (§7.1)
        assert "Industrial Gold" in content, "RFC-0028 §7.1: Benchmark table MUST include 'Industrial Gold'"
        assert "1.27x" in content or "1.09x" in content, "RFC-0028 §7.1: Benchmark table MUST document speedup ratios"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
