import pytest
import sys

# Invoke pytest internals to trigger import cascade
try:
    pytest.main(["--version"])
except SystemExit:
    pass
