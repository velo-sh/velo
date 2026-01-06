# RFC-0011 QA Test Suite: Zygote Worker Integration
# tests/qa/phase_6_1_1/__init__.py

"""
RFC-0011 QA Test Suite

Test tiers:
- L0: Smoke tests (3 tests)
- L1: Feature tests (5 tests)
- L2: Edge cases (5 tests)
- L3: Stress tests (4 tests)
- L4: Security tests (5 tests)
- L5: Performance tests (4 tests)

Total: 26 test cases

Usage:
    # Quick verification
    uv run pytest tests/qa/phase_6_1_1/test_L0_smoke.py -v

    # Full suite
    uv run pytest tests/qa/phase_6_1_1/ -v
"""
