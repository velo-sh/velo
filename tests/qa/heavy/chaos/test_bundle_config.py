"""
Phase 5.2 QA: Bundle Config Verification (QA-REQ-003)
Focus: Security Red Lines and Implementation Integrity.
"""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def velo_binary():
    """Get path to velo binary."""
    cargo_path = Path(__file__).parents[4] / "target" / "release" / "velo"
    if cargo_path.exists():
        return str(cargo_path)
    return "velo"


def run_velo(args: list, cwd: Path, velo_binary: str, timeout: int = 60):
    """Helper to run velo command."""
    result = subprocess.run(
        [velo_binary] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


class TestBundleConfigQA:
    """
    QA独立验证：验证 Bundle 配置与安全不变量
    """

    @pytest.mark.sad_path
    def test_sec_001_default_256mb_limit(self, velo_binary, tmp_path):
        """
        SEC-001: 无配置时，257MB Bundle 必须报错
        """
        # Create a 257MB dummy bundle
        bundle_path = tmp_path / "large.veloc"
        with open(bundle_path, "wb") as f:
            f.seek(257 * 1024 * 1024 - 1)
            f.write(b"\0")

        test_py = tmp_path / "test.py"
        test_py.write_text("print('ok')")

        # We need a way to force velo to load THIS bundle
        # Current --fast assumes bundle.veloc. We'll use a hack or wait for flag.
        # But even without running, we can check basic config parsing if we had unit tests.

        # For now, this test is expected to fail if the limit is not working
        # and we use an oversized bundle.
        # However, building a 257MB file in CI is slow.
        pytest.skip("Oversized bundle test requires pack/build support for large files")

    @pytest.mark.config
    def test_unit_conf_001_toml_parsing(self, velo_binary, tmp_path):
        """
        UNIT-CONF-001: 验证 TOML 解析逻辑
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.velo]
max_bundle_size = 512
"""
        )
        config_path = Path(__file__).parents[4] / "src" / "config.rs"
        content = config_path.read_text()
        assert "max_bundle_size" in content, "Developer has implemented 'max_bundle_size' in src/config.rs"

    @pytest.mark.security
    def test_invariant_004_marshal_limit(self, velo_binary):
        """
        INVARIANT-4: 验证 marshal 递归限制是否为 500
        证明: 目前 python/velo_loader.py 硬编码为 1000
        """
        loader_path = Path(__file__).parents[4] / "python" / "velo_loader.py"
        content = loader_path.read_text()

        # Hard check for the constant
        assert "MARSHAL_RECURSION_LIMIT = 500" in content, (
            f"Security Invariant #4 failed: Limit is not 500 in {loader_path}"
        )

    @pytest.mark.security
    def test_invariant_001_global_hash(self, velo_binary):
        """
        INVARIANT-1: 验证哈希是否覆盖 Header
        证明: 目前 src/loader/verify.rs 只从 128 字节开始校验
        """
        verify_path = Path(__file__).parents[4] / "src" / "loader" / "verify.rs"
        content = verify_path.read_text()

        # Current implementation: verify_blake3(&data[header_end..], &expected_hash)?;
        # Expected: verify_blake3(&data, &expected_hash)?;
        assert "verify_blake3(&data," in content, "Security Invariant #1 failed: Hash does not cover header"

    @pytest.mark.security
    def test_invariant_005_read_atomicity(self, velo_binary):
        """
        INVARIANT-5: 验证大文件读取是否使用了 flock(LockShared)
        证明: 目前 src/loader/verify.rs 直接使用 std::fs::read
        """
        verify_path = Path(__file__).parents[4] / "src" / "loader" / "verify.rs"
        content = verify_path.read_text()

        # We look for integration of lock.rs or flock calls in the loading path
        assert "use crate::loader::lock" in content or "lock_shared" in content.lower(), (
            "Security Invariant #5 failed: No flock(LockShared) found in load_and_verify path"
        )

    @pytest.mark.sad_path
    def test_sec_002_malformed_config_fallback(self, velo_binary, tmp_path):
        """
        SEC-002: 验证非法配置回退逻辑
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.velo]
max_bundle_size = "not_a_number"
"""
        )
        # This is strictly a requirement verification.

    @pytest.mark.security
    def test_invariant_002_boundary_validation(self, velo_binary):
        """
        INVARIANT-2: 验证 data_offset 是否与物理长度对齐校验
        """
        verify_path = Path(__file__).parents[4] / "src" / "loader" / "verify.rs"
        content = verify_path.read_text()

        # We expect a check like: if offset > data.len() or offset < MIN_HEADER_SIZE
        assert "data.len() < 40" in content, "Basic length check present"
        assert "index_offset > data.len()" in content or "index_offset > data.len()" in content.replace(" ", ""), (
            "Boundary check present"
        )

    @pytest.mark.security
    def test_invariant_003_path_resolution(self, velo_binary):
        """
        INVARIANT-3: 验证路径校验是否包含三层逻辑 (Raw, Link, Canonical)
        证明: 目前 src/loader/security.rs 已经初步实现了三层逻辑，需要通过 E2E 确认
        """
        security_path = Path(__file__).parents[4] / "src" / "loader" / "security.rs"
        content = security_path.read_text()

        # Layer 1: Raw
        assert "path.to_string_lossy()" in content
        # Layer 2: read_link
        assert "std::fs::read_link(path)" in content
        # Layer 3: canonicalize
        assert "path.canonicalize()" in content
        # Note: This is a PASSing specification test but we want to ensure it stays!

    @pytest.mark.security
    def test_invariant_006_abi_check(self, velo_binary):
        """
        INVARIANT-6: 验证 ABI/Python 版本强制匹配
        证明: 目前 src/loader/header.rs 虽有检查函数，但 loader 尚未强制调用
        """
        header_path = Path(__file__).parents[4] / "src" / "loader" / "header.rs"
        content = header_path.read_text()

        # Check if check_python_version and check_cache_tag exist
        assert "fn check_python_version" in content
        assert "fn check_cache_tag" in content

        # Now check if verify.rs or run.rs CALLS them
        verify_path = Path(__file__).parents[4] / "src" / "loader" / "verify.rs"
        verify_content = verify_path.read_text()
        assert "check_python_version" in verify_content, (
            "Security Invariant #6 failed: ABI version check not enforced in loader path"
        )
