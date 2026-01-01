"""pytest conftest for Velo QA tests."""
import subprocess
import pytest
import sys
from pathlib import Path

# Add tests/qa to path for imports
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True, scope="module")
def cleanup_zygote_between_modules():
    """Kill any stale Zygote processes and clean sockets before each test module.
    
    This prevents test pollution where one module's Zygote affects another.
    """
    import tempfile
    
    # Clean before module runs
    subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)
    
    # Clean socket files
    sock_path = Path(tempfile.gettempdir()) / "velo-zygote.sock"
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass
    
    yield
    
    # Clean after module completes too
    subprocess.run(["pkill", "-9", "-f", "velo_zygote"], capture_output=True)
    if sock_path.exists():
        try:
            sock_path.unlink()
        except:
            pass
