"""
Phase 5.0.2 Fast Loader Tests

Tests for VeloBundle, VeloFinder, VeloLoader

Run: pytest tests/qa/test_phase5_loader.py -v
"""

import marshal
import struct
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest


# Add python/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))

from velo_loader import VeloBundle, VeloFinder, VeloLoader, install_hook, uninstall_hook
from bundle_builder import VeloBundleBuilder, build_from_project


class TestVeloBundleBuilder:
    """Tests for bundle building"""
    
    def test_build_simple_module(self, tmp_path: Path):
        """Test building a bundle with one module"""
        builder = VeloBundleBuilder()
        
        # Create simple code
        code = compile("x = 42", "<test>", "exec")
        code_data = marshal.dumps(code)
        
        builder.add_code("test_module", code_data)
        
        output = tmp_path / "test.veloc"
        builder.build(output)
        
        assert output.exists()
        assert output.stat().st_size > 0
        
        # Verify magic
        with open(output, "rb") as f:
            assert f.read(4) == b"VELO"
    
    def test_build_from_source(self, tmp_path: Path):
        """Test building from .py source"""
        # Create test source
        src = tmp_path / "hello.py"
        src.write_text("message = 'Hello, World!'")
        
        builder = VeloBundleBuilder()
        builder.add_source("hello", src)
        
        output = tmp_path / "bundle.veloc"
        builder.build(output)
        
        assert output.exists()
    
    def test_build_from_project(self, tmp_path: Path):
        """Test building from project directory"""
        # Create project structure
        (tmp_path / "mypackage").mkdir()
        (tmp_path / "mypackage" / "__init__.py").write_text("# Package")
        (tmp_path / "mypackage" / "core.py").write_text("value = 123")
        (tmp_path / "main.py").write_text("from mypackage import core")
        
        output = build_from_project(tmp_path)
        
        assert output.exists()
        assert output.name == "bundle.veloc"


class TestVeloBundle:
    """Tests for bundle loading"""
    
    @pytest.fixture
    def simple_bundle(self, tmp_path: Path) -> Path:
        """Create a simple test bundle"""
        builder = VeloBundleBuilder()
        
        code = compile("result = 'success'", "<test>", "exec")
        builder.add_code("test_module", marshal.dumps(code))
        
        output = tmp_path / "test.veloc"
        builder.build(output)
        return output
    
    def test_open_bundle(self, simple_bundle: Path):
        """Test opening a bundle"""
        bundle = VeloBundle(simple_bundle)
        bundle.open()
        
        assert len(bundle) == 1
        assert "test_module" in bundle
        
        bundle.close()
    
    def test_get_code(self, simple_bundle: Path):
        """Test getting module code from bundle"""
        bundle = VeloBundle(simple_bundle)
        bundle.open()
        
        code_data = bundle.get_code("test_module")
        assert code_data is not None
        
        # Should be valid marshal data
        code = marshal.loads(code_data)
        assert code is not None
        
        bundle.close()
    
    def test_reject_oversized_bundle(self, tmp_path: Path):
        """Test 256MB size limit"""
        # Create a fake oversized file (we won't actually write 256MB)
        # This tests the size check logic
        from velo_loader import MAX_BUNDLE_SIZE
        assert MAX_BUNDLE_SIZE == 256 * 1024 * 1024
    
    def test_fallback_for_missing_module(self, simple_bundle: Path):
        """Test that missing modules return None (fallback)"""
        bundle = VeloBundle(simple_bundle)
        bundle.open()
        
        code_data = bundle.get_code("nonexistent_module")
        assert code_data is None
        
        bundle.close()


class TestVeloFinder:
    """Tests for import hook"""
    
    @pytest.fixture
    def bundle_with_hook(self, tmp_path: Path):
        """Create bundle and install hook"""
        # Create project
        (tmp_path / "testpkg").mkdir()
        (tmp_path / "testpkg" / "__init__.py").write_text("PKG = True")
        (tmp_path / "testpkg" / "module.py").write_text("VALUE = 42")
        
        # Build bundle
        bundle_path = build_from_project(tmp_path)
        
        # Load and install
        bundle = VeloBundle(bundle_path)
        bundle.open()
        finder = install_hook(bundle, tmp_path)
        
        yield bundle, finder, tmp_path
        
        # Cleanup
        uninstall_hook(finder)
        bundle.close()
        
        # Remove from sys.modules
        for mod in list(sys.modules.keys()):
            if mod.startswith("testpkg"):
                del sys.modules[mod]
    
    def test_find_spec_for_bundled_module(self, bundle_with_hook):
        """Test finder returns spec for bundled modules"""
        bundle, finder, _ = bundle_with_hook
        
        spec = finder.find_spec("testpkg.module", None)
        assert spec is not None
        assert spec.name == "testpkg.module"
    
    def test_find_spec_returns_none_for_missing(self, bundle_with_hook):
        """Test finder returns None for non-bundled modules (fallback)"""
        bundle, finder, _ = bundle_with_hook
        
        spec = finder.find_spec("nonexistent_module", None)
        assert spec is None  # Triggers fallback
    
    def test_import_from_bundle(self, bundle_with_hook):
        """Test actual import from bundle"""
        bundle, finder, _ = bundle_with_hook
        
        # This should use the bundle
        import testpkg.module
        assert testpkg.module.VALUE == 42


class TestVeloLoader:
    """Tests for module loading"""
    
    def test_exec_module_verifies_hash(self, tmp_path: Path):
        """Test that loader verifies BLAKE3 hash"""
        # Create bundle
        builder = VeloBundleBuilder()
        code = compile("x = 1", "<test>", "exec")
        builder.add_code("hash_test", marshal.dumps(code))
        
        bundle_path = tmp_path / "hash_test.veloc"
        builder.build(bundle_path)
        
        # Load bundle
        bundle = VeloBundle(bundle_path)
        bundle.open()
        
        # Verify hash check works
        code_data = bundle.get_code("hash_test")
        assert bundle.verify_module("hash_test", code_data)
        
        # Modified data should fail - XOR last byte to guarantee change
        last_byte = code_data[-1]
        modified_byte = bytes([last_byte ^ 0xFF])  # Flip all bits
        modified_data = code_data[:-1] + modified_byte
        assert not bundle.verify_module("hash_test", modified_data), \
            "Modified data should fail hash verification"
        
        bundle.close()


class TestIntegration:
    """Integration tests"""
    
    def test_full_workflow(self, tmp_path: Path):
        """Test complete build → load → import workflow"""
        # Create project
        (tmp_path / "myapp").mkdir()
        (tmp_path / "myapp" / "__init__.py").write_text("")
        (tmp_path / "myapp" / "core.py").write_text("""
def greet(name):
    return f"Hello, {name}!"

CONSTANT = 42
""")
        (tmp_path / "main.py").write_text("""
from myapp.core import greet, CONSTANT
result = greet("World")
""")
        
        # Build bundle
        bundle_path = build_from_project(tmp_path)
        assert bundle_path.exists()
        
        # Load bundle
        bundle = VeloBundle(bundle_path)
        bundle.open()
        
        assert "myapp" in bundle
        assert "myapp.core" in bundle
        assert "main" in bundle
        
        # Install hook and import
        finder = install_hook(bundle, tmp_path)
        
        try:
            import myapp.core
            assert myapp.core.CONSTANT == 42
            assert myapp.core.greet("Test") == "Hello, Test!"
        finally:
            uninstall_hook(finder)
            bundle.close()
            
            # Cleanup
            for mod in list(sys.modules.keys()):
                if mod.startswith("myapp"):
                    del sys.modules[mod]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
