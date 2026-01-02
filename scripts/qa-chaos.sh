#!/bin/bash
# Phase 3.5 Chaos/Brutal QA Test Script
# Runs only chaos and brutal tests (resource-heavy)
#
# WARNING: These tests may:
#   - Consume significant memory (GB)
#   - Create many processes/threads
#   - Cause system slowdown
#
# Run only when needed for security/stress testing

echo "============================================================"
echo "  Phase 3.5 QA - CHAOS/BRUTAL TESTS"
echo "  ⚠️  WARNING: These tests are resource-heavy!"
echo "============================================================"
echo ""

# Run only brutal tests
uv run python -m pytest tests/qa/test_phase3_5_leader_brutal.py \
    --tb=short \
    -v \
    "$@"

EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  ✅ Chaos tests passed!"
else
    echo "  ❌ Some chaos tests failed (exit code: $EXIT_CODE)"
fi
echo "============================================================"

exit $EXIT_CODE
