"""pytest conftest for Velo QA tests."""
import pytest
import sys
from pathlib import Path

# Add tests/qa to path for imports
sys.path.insert(0, str(Path(__file__).parent))
